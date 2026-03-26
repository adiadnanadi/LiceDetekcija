import os
import json
import base64
import numpy as np
from io import BytesIO
from PIL import Image
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import cv2
from insightface.app import FaceAnalysis
import firebase_admin
from firebase_admin import credentials, firestore
import paho.mqtt.publish as mqtt_publish

app = Flask(__name__)
CORS(app)

# ── Firebase init ─────────────────────────────────────────────
firebase_key_json = os.environ.get("FIREBASE_KEY")
if firebase_key_json:
    cred_dict = json.loads(firebase_key_json)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred, {
    "storageBucket": os.environ.get(
        "FIREBASE_BUCKET", "your-project.appspot.com"
    )
})

db = firestore.client()

# ── MQTT config ───────────────────────────────────────────────
MQTT_BROKER   = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", 1883))
MQTT_TOPIC    = os.environ.get("MQTT_TOPIC", "faceGate/komanda")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

# ── InsightFace model (SINHRONO - ne u thread-u) ─────────────
# Model je već prebačen u Docker image, pa se samo učita iz diska
print("[STARTUP] Učitavam InsightFace buffalo_l model...")
face_app = None
try:
  face_app = FaceAnalysis(
    name="buffalo_sc",
    providers=["CPUExecutionProvider"]
)
face_app.prepare(ctx_id=0, det_size=(320, 320))
    print("[STARTUP] ✅ InsightFace model spreman!")
except Exception as e:
    print(f"[STARTUP] ❌ Greška modela: {e}")


# ── Helper funkcije ──────────────────────────────────────────

def posalji_mqtt(komanda: str):
    try:
        auth = None
        if MQTT_USERNAME:
            auth = {
                "username": MQTT_USERNAME,
                "password": MQTT_PASSWORD
            }
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
    if "," in b64_string:
        b64_string = b64_string.split(",")[1]
    img_bytes = base64.b64decode(b64_string)
    pil_img = Image.open(BytesIO(img_bytes)).convert("RGB")
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def ucitaj_sve_encodinge() -> list:
    korisnici = []
    docs = db.collection("korisnici").stream()
    for doc in docs:
        data = doc.to_dict()
        if "encoding" in data and data["encoding"]:
            korisnici.append({
                "id":       doc.id,
                "ime":      data.get("ime", "Nepoznat"),
                "encoding": data["encoding"],
            })
    return korisnici


def dobavi_embedding(img_bgr: np.ndarray):
    if face_app is None:
        raise Exception(
            "Model nije inicijaliziran — provjeri logove"
        )
    lica = face_app.get(img_bgr)
    if not lica:
        return None
    lice = max(
        lica,
        key=lambda l: (l.bbox[2] - l.bbox[0]) * (l.bbox[3] - l.bbox[1])
    )
    emb = lice.embedding
    return emb / np.linalg.norm(emb)


# ── Endpoints ────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/ping", methods=["GET"])
def ping():
    return "ok", 200


@app.route("/health", methods=["GET"])
def health():
    model_status = "spreman" if face_app is not None else "GREŠKA"
    return jsonify({
        "status": "ok",
        "servis": "FaceGate API",
        "model":  model_status
    })


@app.route("/register", methods=["POST"])
def register():
    try:
        data    = request.get_json()
        ime     = data.get("ime", "").strip()
        email   = data.get("email", "").strip()
        b64_img = data.get("slika", "")

        if not ime or not b64_img:
            return jsonify({"greška": "Nedostaju ime ili slika"}), 400

        img_bgr = base64_u_sliku(b64_img)

        try:
            embedding = dobavi_embedding(img_bgr)
            if embedding is None:
                return jsonify({
                    "greška": "Nije pronađeno lice na slici"
                }), 400
        except Exception as e:
            return jsonify({"greška": str(e)}), 503

        doc_ref = db.collection("korisnici").add({
            "ime":      ime,
            "email":    email,
            "encoding": embedding.tolist(),
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
    try:
        data    = request.get_json()
        b64_img = data.get("slika", "")

        if not b64_img:
            return jsonify({"greška": "Nema slike"}), 400

        img_bgr = base64_u_sliku(b64_img)

        try:
            nepoznati_emb = dobavi_embedding(img_bgr)
        except Exception as e:
            return jsonify({"greška": str(e)}), 503

        if nepoznati_emb is None:
            return jsonify({
                "status":    "nema_lica",
                "poruka":    "Nije pronađeno lice",
                "prepoznat": False,
            })

        korisnici = ucitaj_sve_encodinge()

        if not korisnici:
            return jsonify({
                "status":    "prazan_db",
                "poruka":    "Nema registriranih korisnika",
                "prepoznat": False,
            })

        slicnosti = [
            float(np.dot(nepoznati_emb, np.array(k["encoding"])))
            for k in korisnici
        ]
        max_idx = int(np.argmax(slicnosti))
        max_sim = slicnosti[max_idx]

        prag = 0.6

        print(f"[RECOGNIZE] Sličnost: {max_sim:.3f} (prag: {prag})")

        if max_sim >= prag:
            korisnik   = korisnici[max_idx]
            confidence = round(max_sim * 100, 1)

            db.collection("log_pristupa").add({
                "korisnik_id": korisnik["id"],
                "ime":         korisnik["ime"],
                "status":      "odobren",
                "confidence":  confidence,
                "timestamp":   datetime.utcnow().isoformat(),
            })

            posalji_mqtt("OTVORI")

            print(f"[RECOGNIZE] ✅ {korisnik['ime']} ({confidence}%)")
            return jsonify({
                "status":     "prepoznat",
                "prepoznat":  True,
                "ime":        korisnik["ime"],
                "confidence": confidence,
                "poruka":     f"Dobrodošao, {korisnik['ime']}!",
            })
        else:
            db.collection("log_pristupa").add({
                "ime":       "Nepoznata osoba",
                "status":    "odbijen",
                "timestamp": datetime.utcnow().isoformat(),
            })

            posalji_mqtt("ALARM")

            print(f"[RECOGNIZE] ❌ Nepoznat (sim={max_sim:.3f})")
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
    try:
        db.collection("korisnici").document(korisnik_id).delete()
        return jsonify({"poruka": "Korisnik obrisan"})
    except Exception as e:
        return jsonify({"greška": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
