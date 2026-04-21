/*
 * Smart Pet Feeder — ESP32 Firmware
 *
 * Libraries required (install via Arduino Library Manager):
 *   - ArduinoJson   (v7+)
 *   - MFRC522
 *   - HX711
 *   - RTClib
 *   - ESP32Servo
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <SPI.h>
#include <MFRC522.h>
#include <HX711.h>
#include <RTClib.h>
#include <ESP32Servo.h>

// ── 1. NETWORK SETTINGS ──────────────────────────────────────────────────────
// Add all your networks here. The ESP32 will try each one in order until
// one connects. Replace the example names and passwords with your real ones.

struct WifiNetwork {
  const char* ssid;
  const char* password;
};

const WifiNetwork WIFI_NETWORKS[] = {
  { "HOME_WIFI_NAME",      "renuwifi"      },  // e.g. your home router
  { "UNI_WIFI_NAME",       "HCK_Connect"       },  // e.g. university WiFi
  { "HOTSPOT_WIFI_NAME",   "suyank123"   },  // e.g. your phone hotspot
};
const int WIFI_NETWORK_COUNT = sizeof(WIFI_NETWORKS) / sizeof(WIFI_NETWORKS[0]);

// ── YOUR LAPTOP'S LOCAL IP ────────────────────────────────────────────────────
// Run `ipconfig` (Windows) or `ifconfig` (Mac/Linux) to find it.
// It will look like 192.168.x.x — update this whenever you switch networks.
const char* FLASK_URL = "http://192.168.1.100:5000";

// ── 2. PIN DEFINITIONS ───────────────────────────────────────────────────────
#define HX711_DOUT  4
#define HX711_SCK   5
#define SERVO_PIN   13
#define RFID_SS     15
#define RFID_RST    27
#define RTC_SDA     21
#define RTC_SCL     22
#define BUZZER_PIN  25

// ── 3. OPERATIONAL CONSTANTS ─────────────────────────────────────────────────
const int   SERVO_CLOSED       = 0;
const int   SERVO_OPEN         = 90;
const float CALIBRATION_FACTOR = 2280.0f; // Tune this for your load cell

const unsigned long HEARTBEAT_INT   = 60000UL; // 60 s — keep dashboard "Online"
const unsigned long POLL_INT        =  5000UL; //  5 s — check for web commands
const unsigned long COOLDOWN_INT    = 15000UL; // 15 s — anti-double-feed guard
const unsigned long WIFI_RETRY_INT  = 10000UL; // 10 s — reconnect attempt rate
const unsigned long WIFI_TIMEOUT_MS = 15000UL; // 15 s — max wait per network

// Maximum pets the device can cache locally
const int MAX_PETS = 20;

// ── 4. OBJECTS & STATE ───────────────────────────────────────────────────────
HX711      scale;
RTC_DS3231 rtc;
bool       rtcAvailable = false;
Servo      feederServo;
MFRC522    rfid(RFID_SS, RFID_RST);

struct Pet {
  String rfid;
  String name;
  float  portion;
};

Pet  knownPets[MAX_PETS];
int  petCount      = 0;

unsigned long lastHeartbeat = 0;
unsigned long lastPoll      = 0;
unsigned long lastFeed      = 0;
unsigned long lastWifiRetry = 0;

// ── 5. WIFI HELPERS ──────────────────────────────────────────────────────────

/*
 * connectWiFi — tries every network in WIFI_NETWORKS in order.
 * Waits up to WIFI_TIMEOUT_MS per network before moving to the next.
 * Returns true if any network connects, false if all fail.
 */
bool connectWiFi() {
  for (int i = 0; i < WIFI_NETWORK_COUNT; i++) {
    Serial.printf("[WiFi] Trying network %d/%d: %s ...\n",
                  i + 1, WIFI_NETWORK_COUNT, WIFI_NETWORKS[i].ssid);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_NETWORKS[i].ssid, WIFI_NETWORKS[i].password);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
      if (millis() - start > WIFI_TIMEOUT_MS) {
        Serial.printf("[WiFi] %s timed out — trying next.\n",
                      WIFI_NETWORKS[i].ssid);
        WiFi.disconnect();
        delay(500);
        break;
      }
      delay(500);
      Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("\n[WiFi] Connected to: %s\n", WIFI_NETWORKS[i].ssid);
      Serial.printf("[WiFi] IP address:   %s\n",
                    WiFi.localIP().toString().c_str());
      return true;
    }
  }

  Serial.println("[WiFi] All networks failed — will retry later.");
  return false;
}

/*
 * ensureWiFi — called at the top of every network function.
 * If the link is down, attempts a reconnect at most once per WIFI_RETRY_INT.
 * Returns true if we have a live connection.
 */
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  unsigned long now = millis();
  if (now - lastWifiRetry < WIFI_RETRY_INT) return false;
  lastWifiRetry = now;

  Serial.println("[WiFi] Connection lost — reconnecting...");
  return connectWiFi();
}

// ── 6. SETUP ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  // RTC — non-fatal if absent; log a warning instead of hanging
  Wire.begin(RTC_SDA, RTC_SCL);
  if (!rtc.begin()) {
    Serial.println("[RTC] WARNING: Not detected. Check wiring.");
  } else {
    rtcAvailable = true;
    Serial.println("[RTC] OK");
  }

  // Scale
  scale.begin(HX711_DOUT, HX711_SCK);
  scale.set_scale(CALIBRATION_FACTOR);
  scale.tare();
  Serial.println("[Scale] Tared.");

  // Servo
  feederServo.attach(SERVO_PIN);
  feederServo.write(SERVO_CLOSED);

  // RFID
  SPI.begin();
  rfid.PCD_Init();
  Serial.println("[RFID] Ready.");

  // WiFi — tries all networks; continues even if all fail
  connectWiFi();

  // Pull pet list from server (safe to call even if WiFi is down)
  syncPets();

  beep(2, 100);
  Serial.println(">>> SYSTEM READY");
}

// ── 7. MAIN LOOP ─────────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // RFID scan — skip while in cooldown so a pet can't double-trigger
  if (now - lastFeed > COOLDOWN_INT) {
    if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
      handleRFID();
    }
  }

  // Poll server for web/schedule commands
  if (now - lastPoll > POLL_INT) {
    lastPoll = now;
    checkServerCommands();
  }

  // Heartbeat — keeps the dashboard "Online" indicator alive
  if (now - lastHeartbeat > HEARTBEAT_INT) {
    lastHeartbeat = now;
    sendHeartbeat();
  }
}

// ── 8. FEEDING LOGIC ─────────────────────────────────────────────────────────
/*
 * dispense — opens the servo for a time proportional to targetGrams,
 * then measures the actual weight change.
 *
 * NOTE: delay() here intentionally blocks the loop. During dispensing
 * (~7 s for 50 g) RFID and polling are paused. This is acceptable for
 * the current hardware design. If you need true non-blocking dispensing,
 * replace the delay with a millis()-based state machine.
 */
float dispense(float targetGrams, const String& petName) {
  Serial.printf("[Dispense] Starting for %s (target %.1f g)\n",
                petName.c_str(), targetGrams);
  beep(1, 300);

  // Re-tare before measuring so bowl placement after boot doesn't skew results
  scale.tare();
  delay(500);

  float weightBefore = getWeight();
  feederServo.write(SERVO_OPEN);

  delay((unsigned long)(targetGrams * 150)); // ~150 ms per gram

  feederServo.write(SERVO_CLOSED);
  delay(1000); // Let food settle on the scale

  float weightAfter = getWeight();
  float actual = max(0.0f, weightAfter - weightBefore);

  Serial.printf("[Dispense] Done. Actual: %.2f g\n", actual);
  lastFeed = millis();
  return actual;
}

// ── 9. RFID HANDLER ──────────────────────────────────────────────────────────
void handleRFID() {
  // Build uppercase hex UID string
  String tag = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) tag += "0";
    tag += String(rfid.uid.uidByte[i], HEX);
  }
  tag.toUpperCase();
  Serial.printf("[RFID] Tag detected: %s\n", tag.c_str());

  bool matched = false;
  for (int i = 0; i < petCount; i++) {
    if (knownPets[i].rfid.equalsIgnoreCase(tag)) {
      float dispensed = dispense(knownPets[i].portion, knownPets[i].name);
      logFeed(knownPets[i].name, dispensed, "rfid");
      matched = true;
      break;
    }
  }

  if (!matched) {
    Serial.printf("[RFID] Unknown tag: %s\n", tag.c_str());
    beep(3, 80); // 3 short beeps = unrecognised tag
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

// ── 10. SERVER COMMUNICATION ─────────────────────────────────────────────────
void checkServerCommands() {
  if (!ensureWiFi()) return;

  HTTPClient http;
  http.begin(String(FLASK_URL) + "/api/command");
  int code = http.GET();

  if (code == 200) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, http.getString());

    if (err) {
      Serial.printf("[Poll] JSON parse error: %s\n", err.c_str());
    } else if (doc["command"] == "feed") {
      float  grams    = doc["grams"]    | 50.0f;
      String petName  = doc["pet_name"] | "WebUser";
      float  dispensed = dispense(grams, petName);
      logFeed(petName, dispensed, "web");
    }
  } else if (code > 0) {
    Serial.printf("[Poll] Server returned HTTP %d\n", code);
  } else {
    Serial.printf("[Poll] Request failed: %s\n", http.errorToString(code).c_str());
  }
  http.end();
}

void logFeed(const String& name, float grams, const String& src) {
  if (!ensureWiFi()) {
    Serial.println("[logFeed] No WiFi — feed not logged to server.");
    return;
  }

  HTTPClient http;
  http.begin(String(FLASK_URL) + "/api/feed");
  http.addHeader("Content-Type", "application/json");

  JsonDocument doc;
  doc["pet_name"] = name;
  doc["grams"]    = grams;
  doc["source"]   = src;

  String body;
  serializeJson(doc, body);

  int code = http.POST(body);
  if (code != 200 && code != 201) {
    Serial.printf("[logFeed] POST failed with code %d\n", code);
  }
  http.end();
}

void syncPets() {
  if (!ensureWiFi()) {
    Serial.println("[syncPets] No WiFi — keeping existing pet cache.");
    return;
  }

  HTTPClient http;
  http.begin(String(FLASK_URL) + "/api/pets");
  int code = http.GET();

  if (code != 200) {
    Serial.printf("[syncPets] Server returned %d — cache unchanged.\n", code);
    http.end();
    return;
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, http.getString());
  http.end();

  if (err) {
    Serial.printf("[syncPets] JSON parse error: %s — cache unchanged.\n", err.c_str());
    return;
  }

  JsonArray arr = doc.as<JsonArray>();
  int loaded = 0;
  for (JsonObject p : arr) {
    if (loaded >= MAX_PETS) {
      Serial.printf("[syncPets] WARNING: More than %d pets on server — extras ignored.\n",
                    MAX_PETS);
      break;
    }
    knownPets[loaded] = { p["rfid"] | "", p["name"] | "Pet", p["portion"] | 50.0f };
    loaded++;
  }
  petCount = loaded;
  Serial.printf("[syncPets] Loaded %d pet(s).\n", petCount);
}

void sendHeartbeat() {
  if (!ensureWiFi()) return;

  HTTPClient http;
  http.begin(String(FLASK_URL) + "/device/online");
  int code = http.GET();
  if (code != 200) {
    Serial.printf("[Heartbeat] Unexpected response: %d\n", code);
  }
  http.end();
}

// ── 11. UTILITIES ────────────────────────────────────────────────────────────
float getWeight() {
  if (!scale.is_ready()) return 0.0f;
  return scale.get_units(10);
}

void beep(int times, int ms) {
  for (int i = 0; i < times; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(ms);
    digitalWrite(BUZZER_PIN, LOW);
    delay(ms / 2);
  }
}
