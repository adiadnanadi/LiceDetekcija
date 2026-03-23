import os
import json
import base64
import numpy as np
from io import BytesIO
from PIL import Image
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import face_recognition
import firebase_admin
from firebase_admin import credentials, firestore, storage
import paho.mqtt.publish as mqtt_publish

app = Flask(__name__)
CORS(app)

# ── Firebase init ──────────────────────────────────────────────────────────────
firebase_key_json = os.environ.get("FIREBASE_KEY")
if firebase_key_json:
    cred_dict = json.loads(firebase_key_json)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred, {
    "storageBucket": os.environ.get("FIREBASE_BUCKET", "your-project.appspot.com")
})

db = firestore.client()

# ── MQTT config ────────────────────────────────────────────────────────────────
MQTT_BROKER   = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", 1883))
MQTT_TOPIC    = os.environ.get("MQTT_TOPIC", "faceGate/komanda")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")


def posalji_mqtt(komanda: str):
    """Pošalji komandu ESP8266-u putem MQTT brokera."""
    try:
        auth = None
        if MQTT_USERNAME:
            auth = {"username": MQTT_USERNAME, "password": MQTT_PASSWORD}
        mqtt_publish.single(
            topic=MQTT_TOPIC,
            payload=komanda,
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
            auth=auth,
        )
        print(f"[MQTT] Poslano: {komanda}")
    except Exception as e:
        print(f"[MQTT] Greška: {e}")


def base64_u_sliku(b64_string: str) -> np.ndarray:
    """Konvertuj base64 string u numpy array za face_recognition."""
    if "," in b64_string:
        b64_string = b64_string.split(",")[1]
    img_bytes = base64.b64decode(b64_string)
    pil_img = Image.open(BytesIO(img_bytes)).convert("RGB")
    return np.array(pil_img)


def ucitaj_sve_encodinge() -> list:
    """Učitaj sve registrirane korisnike i njihove face encodinge iz Firestorea."""
    korisnici = []
    docs = db.collection("korisnici").stream()
    for doc in docs:
        data = doc.to_dict()
        if "encoding" in data and data["encoding"]:
            korisnici.append({
                "id":       doc.id,
                "ime":      data.get("ime", "Nepoznat"),
                "encoding": np.array(data["encoding"]),
            })
    return korisnici


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servis": "FaceGate API"})


@app.route("/register", methods=["POST"])
def register():
    """
    Registruj novog korisnika.
    Body: { "ime": "Adnan", "email": "...", "slika": "<base64>" }
    """
    try:
        data    = request.get_json()
        ime     = data.get("ime", "").strip()
        email   = data.get("email", "").strip()
        b64_img = data.get("slika", "")

        if not ime or not b64_img:
            return jsonify({"greška": "Nedostaju ime ili slika"}), 400

        img_array = base64_u_sliku(b64_img)
        lica      = face_recognition.face_locations(img_array)

        if not lica:
            return jsonify({"greška": "Nije pronađeno lice na slici"}), 400

        encoding = face_recognition.face_encodings(img_array, lica)[0]

        # Spremi u Firestore
        doc_ref = db.collection("korisnici").add({
            "ime":      ime,
            "email":    email,
            "encoding": encoding.tolist(),
            "datum":    datetime.utcnow().isoformat(),
            "aktivan":  True,
        })

        print(f"[REGISTER] Registriran: {ime} ({doc_ref[1].id})")
        return jsonify({
            "poruka": f"Korisnik '{ime}' uspješno registriran!",
            "id":     doc_ref[1].id,
        })

    except Exception as e:
        print(f"[REGISTER] Greška: {e}")
        return jsonify({"greška": str(e)}), 500


@app.route("/recognize", methods=["POST"])
def recognize():
    """
    Prepoznaj lice s kamere.
    Body: { "slika": "<base64>" }
    """
    try:
        data    = request.get_json()
        b64_img = data.get("slika", "")

        if not b64_img:
            return jsonify({"greška": "Nema slike"}), 400

        img_array = base64_u_sliku(b64_img)
        lica      = face_recognition.face_locations(img_array)

        if not lica:
            return jsonify({
                "status":    "nema_lica",
                "poruka":    "Nije pronađeno lice",
                "prepoznat": False,
            })

        nepoznati_encoding = face_recognition.face_encodings(img_array, lica)[0]
        korisnici          = ucitaj_sve_encodinge()

        if not korisnici:
            return jsonify({
                "status":    "prazan_db",
                "poruka":    "Nema registriranih korisnika",
                "prepoznat": False,
            })

        poznati_encodinzi = [k["encoding"] for k in korisnici]
        udaljenosti       = face_recognition.face_distance(poznati_encodinzi, nepoznati_encoding)
        min_idx           = int(np.argmin(udaljenosti))
        min_dist          = float(udaljenosti[min_idx])
        prag              = 0.50  # stricter = manji prag

        if min_dist < prag:
            korisnik   = korisnici[min_idx]
            confidence = round((1 - min_dist) * 100, 1)

            # Log u Firestore
            db.collection("log_pristupa").add({
                "korisnik_id": korisnik["id"],
                "ime":         korisnik["ime"],
                "status":      "odobren",
                "confidence":  confidence,
                "timestamp":   datetime.utcnow().isoformat(),
            })

            # Pošalji ESP8266-u
            posalji_mqtt("OTVORI")

            print(f"[RECOGNIZE] Prepoznat: {korisnik['ime']} ({confidence}%)")
            return jsonify({
                "status":     "prepoznat",
                "prepoznat":  True,
                "ime":        korisnik["ime"],
                "confidence": confidence,
                "poruka":     f"Dobrodošao, {korisnik['ime']}!",
            })
        else:
            # Log nepoznate osobe
            db.collection("log_pristupa").add({
                "ime":      "Nepoznata osoba",
                "status":   "odbijen",
                "timestamp": datetime.utcnow().isoformat(),
            })

            posalji_mqtt("ALARM")

            print(f"[RECOGNIZE] Nepoznato lice (dist={min_dist:.3f})")
            return jsonify({
                "status":    "nepoznat",
                "prepoznat": False,
                "poruka":    "Pristup odbijen — nepoznata osoba",
            })

    except Exception as e:
        print(f"[RECOGNIZE] Greška: {e}")
        return jsonify({"greška": str(e)}), 500


@app.route("/korisnici", methods=["GET"])
def lista_korisnika():
    """Vrati listu registriranih korisnika (bez encodinga)."""
    try:
        docs = db.collection("korisnici").stream()
        lista = []
        for doc in docs:
            d = doc.to_dict()
            lista.append({
                "id":    doc.id,
                "ime":   d.get("ime"),
                "email": d.get("email"),
                "datum": d.get("datum"),
            })
        return jsonify({"korisnici": lista, "ukupno": len(lista)})
    except Exception as e:
        return jsonify({"greška": str(e)}), 500


@app.route("/log", methods=["GET"])
def log_pristupa():
    """Vrati posljednjih 50 zapisa pristupa."""
    try:
        docs = (
            db.collection("log_pristupa")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(50)
            .stream()
        )
        zapisi = [{"id": d.id, **d.to_dict()} for d in docs]
        return jsonify({"log": zapisi})
    except Exception as e:
        return jsonify({"greška": str(e)}), 500


@app.route("/korisnici/<korisnik_id>", methods=["DELETE"])
def obrisi_korisnika(korisnik_id):
    """Obriši korisnika iz sistema."""
    try:
        db.collection("korisnici").document(korisnik_id).delete()
        return jsonify({"poruka": "Korisnik obrisan"})
    except Exception as e:
        return jsonify({"greška": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
