#include <WiFi.h>
#include <HTTPClient.h>

NEW SKETCH

#include <ArduinoJson.h>
#include <Wire.h>
#include <SPI.h>
#include <MFRC522.h>
#include <HX711.h>
#include <RTClib.h>
#include <ESP32Servo.h>

// ── 1. NETWORK SETTINGS ──────────────────────────────────────
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* FLASK_URL = "http://127.0.0.1:5000"; // Use your Laptop's IP

// ── 2. PIN DEFINITIONS ───────────────────────────────────────
#define HX711_DOUT  4
#define HX711_SCK   5
#define SERVO_PIN   13
#define RFID_SS     15
#define RFID_RST    27
#define RTC_SDA     21
#define RTC_SCL     22
#define BUZZER_PIN  25

// ── 3. OPERATIONAL CONSTANTS ────────────────────────────────
const int   SERVO_CLOSED     = 0;
const int   SERVO_OPEN       = 90;
const float BOWL_EMPTY_LIMIT = 10.0;  // Grams considered "empty"
const float CALIBRATION_FACTOR = 2280.0f; // Adjust this via testing

const unsigned long HEARTBEAT_INT  = 60000; // 1 Minute
const unsigned long POLL_INT       = 5000;  // 5 Seconds
const unsigned long COOLDOWN_INT   = 15000; // 15 Seconds (anti-double feed)

// ── 4. OBJECTS & STATE ──────────────────────────────────────
HX711       scale;
RTC_DS3231  rtc;
Servo       feederServo;
MFRC522     rfid(RFID_SS, RFID_RST);

struct Pet {
  String rfid;
  String name;
  float  portion;
};

Pet knownPets[10];
int petCount = 0;
unsigned long lastHeartbeat = 0, lastPoll = 0, lastFeed = 0;

// ── 5. SETUP ────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  // Initialize Hardware
  Wire.begin(RTC_SDA, RTC_SCL);
  rtc.begin();
  
  scale.begin(HX711_DOUT, HX711_SCK);
  scale.set_scale(CALIBRATION_FACTOR);
  scale.tare();

  feederServo.attach(SERVO_PIN);
  feederServo.write(SERVO_CLOSED);

  SPI.begin();
  rfid.PCD_Init();

  connectWiFi();
  syncPets();
  beep(2, 100);
  Serial.println(">>> SYSTEM READY");
}

// ── 6. MAIN LOOP ─────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // 1. Check for RFID Tag (if not in cooldown)
  if (now - lastFeed > COOLDOWN_INT) {
    if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
      handleRFID();
    }
  }

  // 2. Poll Server for Web/Scheduled Commands
  if (now - lastPoll > POLL_INT) {
    lastPoll = now;
    checkServerCommands();
  }

  // 3. Send Heartbeat (keeps device 'Online' in Dashboard)
  if (now - lastHeartbeat > HEARTBEAT_INT) {
    lastHeartbeat = now;
    sendHeartbeat();
  }
}

// ── 7. FEEDING LOGIC ────────────────────────────────────────
float dispense(float targetGrams, String petName) {
  Serial.println("Dispensing for: " + petName);
  beep(1, 300);
  
  float weightBefore = getWeight();
  feederServo.write(SERVO_OPEN);
  
  // Dynamic delay based on grams (e.g., 100ms per gram)
  delay(targetGrams * 150); 
  
  feederServo.write(SERVO_CLOSED);
  delay(1000); // Wait for scale to settle
  
  float weightAfter = getWeight();
  float actual = max(0.0f, weightAfter - weightBefore);
  
  Serial.printf("Actual Dispensed: %.2fg\n", actual);
  lastFeed = millis();
  return actual;
}

// ── 8. COMMUNICATION ────────────────────────────────────────
void checkServerCommands() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  HTTPClient http;
  http.begin(String(FLASK_URL) + "/api/command");
  int code = http.GET();

  if (code == 200) {
    DynamicJsonDocument doc(512);
    DeserializationError err = deserializeJson(doc, http.getString());
    
    if (!err && doc["command"] == "feed") {
      float dispensed = dispense(doc["grams"] | 50.0f, doc["pet_name"] | "WebUser");
      logFeed(doc["pet_name"] | "WebUser", dispensed, "web");
    }
  }
  http.end();
}

void logFeed(String name, float grams, String src) {
  HTTPClient http;
  http.begin(String(FLASK_URL) + "/api/feed");
  http.addHeader("Content-Type", "application/json");
  
  String body;
  StaticJsonDocument<128> doc;
  doc["pet_name"] = name;
  doc["grams"] = grams;
  doc["source"] = src;
  serializeJson(doc, body);
  
  http.POST(body);
  http.end();
}

// ── 9. UTILS ────────────────────────────────────────────────
void handleRFID() {
  String tag = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    tag += String(rfid.uid.uidByte[i] < 0x10 ? "0" : "");
    tag += String(rfid.uid.uidByte[i], HEX);
  }
  tag.toUpperCase();

  for (int i = 0; i < petCount; i++) {
    if (knownPets[i].rfid.equalsIgnoreCase(tag)) {
      float dispensed = dispense(knownPets[i].portion, knownPets[i].name);
      logFeed(knownPets[i].name, dispensed, "rfid");
      break;
    }
  }
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

float getWeight() {
  return scale.is_ready() ? scale.get_units(10) : 0.0f;
}

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nIP: " + WiFi.localIP().toString());
}

void syncPets() {
  HTTPClient http;
  http.begin(String(FLASK_URL) + "/api/pets");
  if (http.GET() == 200) {
    DynamicJsonDocument doc(2048);
    deserializeJson(doc, http.getString());
    JsonArray arr = doc.as<JsonArray>();
    petCount = 0;
    for (JsonObject p : arr) {
      if (petCount < 10) {
        knownPets[petCount] = {p["rfid"] | "", p["name"] | "Pet", p["portion"] | 50.0f};
        petCount++;
      }
    }
  }
  http.end();
}

void sendHeartbeat() {
  HTTPClient http;
  http.begin(String(FLASK_URL) + "/device/online");
  http.GET();
  http.end();
}

void beep(int times, int ms) {
  for (int i = 0; i < times; i++) {
    digitalWrite(BUZZER_PIN, HIGH); delay(ms);
    digitalWrite(BUZZER_PIN, LOW); delay(ms/2);
  }
}