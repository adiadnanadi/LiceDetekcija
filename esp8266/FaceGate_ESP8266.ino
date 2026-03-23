/*
 * FaceGate — ESP8266 MQTT Controller
 * ====================================
 * Spoji se na HiveMQ MQTT broker i čeka komande:
 *   "OTVORI" → servo na 90°, zelena LED, 5 sekundi, zatim nazad
 *   "ALARM"  → crvena LED trepće, servo ostaje zatvoren
 *
 * Biblioteke potrebne (instaliraj kroz Arduino Library Manager):
 *   - PubSubClient  by Nick O'Leary
 *   - ESP8266WiFi   (dolazi s ESP8266 board packageom)
 *   - Servo         (standardna Arduino biblioteka)
 *
 * Board settings u Arduino IDE:
 *   Board: NodeMCU 1.0 (ESP-12E Module)
 *   Upload Speed: 115200
 *   Flash Size: 4MB (FS:2MB OTA:1019KB)
 */

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <Servo.h>

// ── WiFi konfiguracija ─────────────────────────────────────────────────────────
const char* WIFI_SSID     = "TVOJA_WIFI_MREZA";   // ← promijeni
const char* WIFI_PASSWORD = "TVOJA_WIFI_LOZINKA"; // ← promijeni

// ── MQTT konfiguracija ─────────────────────────────────────────────────────────
const char* MQTT_BROKER   = "broker.hivemq.com";  // besplatan javni broker
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC    = "faceGate/komanda";   // mora biti isto kao u .env
const char* MQTT_CLIENT   = "FaceGate_ESP8266";   // jedinstveni ID

// Ako koristiš autentikaciju (HiveMQ Cloud):
// const char* MQTT_USER  = "username";
// const char* MQTT_PASS  = "password";

// ── Pinovi ────────────────────────────────────────────────────────────────────
#define SERVO_PIN   D1   // GPIO5  — bijela žica servo motora
#define LED_GREEN   D2   // GPIO4  — zelena LED (odobrenje)
#define LED_RED     D3   // GPIO0  — crvena LED (alarm)
#define BUZZER_PIN  D4   // GPIO2  — buzzer (opciono, zakomentiraj ako nemas)

// ── Servo pozicije ────────────────────────────────────────────────────────────
#define SERVO_ZATVOREN   0    // stupnjeva — rama zatvorena
#define SERVO_OTVOREN   90    // stupnjeva — rama otvorena

// ── Trajanje ──────────────────────────────────────────────────────────────────
#define TRAJANJE_OTVORENO  5000   // ms koliko rama ostaje otvorena
#define TRAJANJE_ALARMA    3000   // ms trajanje alarm sekvence

// ── Objekti ───────────────────────────────────────────────────────────────────
WiFiClient   espClient;
PubSubClient mqttClient(espClient);
Servo        servo;

// ── Stanje ────────────────────────────────────────────────────────────────────
bool  ramaOtvorena  = false;
unsigned long ramaVrijeme = 0;


// ════════════════════════════════════════════════════════════════════════════════
// MQTT callback — poziva se kad stigne poruka
// ════════════════════════════════════════════════════════════════════════════════
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Pretvori payload u String
  String poruka = "";
  for (unsigned int i = 0; i < length; i++) {
    poruka += (char)payload[i];
  }

  Serial.print("[MQTT] Primljeno na topiku '");
  Serial.print(topic);
  Serial.print("': ");
  Serial.println(poruka);

  // ── OTVORI — prepoznata osoba ──────────────────────────────────────────────
  if (poruka == "OTVORI") {
    Serial.println("[ACTION] Otvaranje rame...");

    // Ugasi crvenu, upali zelenu
    digitalWrite(LED_RED,   LOW);
    digitalWrite(LED_GREEN, HIGH);

    // Kratki beep (odobrenje)
    #ifdef BUZZER_PIN
      tone(BUZZER_PIN, 1000, 200);
      delay(250);
      tone(BUZZER_PIN, 1500, 150);
    #endif

    // Otvori servo
    servo.write(SERVO_OTVOREN);
    ramaOtvorena  = true;
    ramaVrijeme   = millis();

    Serial.println("[ACTION] Rama otvorena, čekam " + String(TRAJANJE_OTVORENO/1000) + " sek...");
  }

  // ── ALARM — nepoznata osoba ────────────────────────────────────────────────
  else if (poruka == "ALARM") {
    Serial.println("[ACTION] ALARM — nepoznata osoba!");

    // Zatvori ramu sigurno
    servo.write(SERVO_ZATVOREN);
    ramaOtvorena = false;

    // Trepćuća crvena LED + alarm zvuk
    unsigned long startTime = millis();
    while (millis() - startTime < TRAJANJE_ALARMA) {
      digitalWrite(LED_GREEN, LOW);
      digitalWrite(LED_RED, HIGH);
      #ifdef BUZZER_PIN
        tone(BUZZER_PIN, 800, 100);
      #endif
      delay(200);

      digitalWrite(LED_RED, LOW);
      delay(200);
    }

    // Ugasi sve nakon alarma
    digitalWrite(LED_RED,   LOW);
    digitalWrite(LED_GREEN, LOW);
    noTone(BUZZER_PIN);
    Serial.println("[ACTION] Alarm završen.");
  }

  // ── ZATVORI — ručno zatvaranje ─────────────────────────────────────────────
  else if (poruka == "ZATVORI") {
    Serial.println("[ACTION] Ručno zatvaranje rame...");
    servo.write(SERVO_ZATVOREN);
    digitalWrite(LED_GREEN, LOW);
    ramaOtvorena = false;
  }

  // ── TEST — provjera konekcije ──────────────────────────────────────────────
  else if (poruka == "TEST") {
    Serial.println("[ACTION] Test primljen — ESP8266 radi!");
    // Kratka sekvenca za potvrdu
    for (int i = 0; i < 3; i++) {
      digitalWrite(LED_GREEN, HIGH);
      delay(100);
      digitalWrite(LED_GREEN, LOW);
      delay(100);
    }
  }
}


// ════════════════════════════════════════════════════════════════════════════════
// WiFi konekcija
// ════════════════════════════════════════════════════════════════════════════════
void connectWiFi() {
  Serial.print("[WiFi] Spajam se na ");
  Serial.print(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int pokuseji = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    pokuseji++;

    // LED trepći dok se spaja
    digitalWrite(LED_GREEN, pokuseji % 2);

    if (pokuseji > 40) {
      Serial.println("\n[WiFi] GREŠKA — resetujem...");
      ESP.restart();
    }
  }

  digitalWrite(LED_GREEN, LOW);
  Serial.println("\n[WiFi] Spojeno!");
  Serial.print("[WiFi] IP adresa: ");
  Serial.println(WiFi.localIP());
}


// ════════════════════════════════════════════════════════════════════════════════
// MQTT konekcija
// ════════════════════════════════════════════════════════════════════════════════
void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("[MQTT] Spajam se na broker...");

    // Bez autentikacije:
    bool connected = mqttClient.connect(MQTT_CLIENT);
    // Sa autentikacijom (odkomentiraj ako trebaš):
    // bool connected = mqttClient.connect(MQTT_CLIENT, MQTT_USER, MQTT_PASS);

    if (connected) {
      Serial.println(" Spojeno!");

      // Subscribe na topic
      mqttClient.subscribe(MQTT_TOPIC);
      Serial.print("[MQTT] Pretplaćen na: ");
      Serial.println(MQTT_TOPIC);

      // Pošalji status poruku da javimo da smo online
      mqttClient.publish("faceGate/status", "ONLINE");

    } else {
      Serial.print(" Greška, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" — pokušavam za 3 sek...");

      // Trepni crvenom na grešku
      digitalWrite(LED_RED, HIGH);
      delay(3000);
      digitalWrite(LED_RED, LOW);
    }
  }
}


// ════════════════════════════════════════════════════════════════════════════════
// SETUP
// ════════════════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n\n=== FaceGate ESP8266 ===");

  // Pinovi
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED,   OUTPUT);
  #ifdef BUZZER_PIN
    pinMode(BUZZER_PIN, OUTPUT);
  #endif

  // Servo — startuj zatvoren
  servo.attach(SERVO_PIN);
  servo.write(SERVO_ZATVOREN);
  delay(500);

  // Inicijalni LED test
  Serial.println("[SETUP] LED test...");
  digitalWrite(LED_GREEN, HIGH); delay(300);
  digitalWrite(LED_RED,   HIGH); delay(300);
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED,   LOW);

  // WiFi
  connectWiFi();

  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setKeepAlive(60);
  connectMQTT();

  Serial.println("[SETUP] FaceGate spreman!");
}


// ════════════════════════════════════════════════════════════════════════════════
// LOOP
// ════════════════════════════════════════════════════════════════════════════════
void loop() {
  // Reconnect ako je pala veza
  if (!mqttClient.connected()) {
    Serial.println("[LOOP] MQTT veza prekinuta — reconnect...");
    connectMQTT();
  }

  mqttClient.loop();

  // Auto-zatvori ramu nakon isteka vremena
  if (ramaOtvorena && (millis() - ramaVrijeme >= TRAJANJE_OTVORENO)) {
    Serial.println("[LOOP] Zatvaranje rame (timeout)...");
    servo.write(SERVO_ZATVOREN);
    digitalWrite(LED_GREEN, LOW);
    ramaOtvorena = false;
  }

  // WiFi watchdog — resetuj ako nema mreže
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[LOOP] WiFi izgubljen — reconnect...");
    connectWiFi();
    connectMQTT();
  }
}
