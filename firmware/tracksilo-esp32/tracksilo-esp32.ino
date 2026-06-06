/*
 * TrackSilo - Firmware del sensor ESP32 + DHT22 para CafeLab.
 *
 * Flujo:
 *   1. WiFiManager: si no hay WiFi guardado, abre el AP "TrackSilo-Setup" con
 *      portal cautivo para que el usuario ingrese la red del cafe.
 *   2. mDNS: resuelve el edge en "cafelab-edge.local" (sin IP fija).
 *   3. Loop: lee el DHT22 y hace POST /api/v1/edge/readings con la API key.
 *      Aplica el actuatorCommand de la respuesta (deshumedecedor / LED).
 *
 * La deviceId y la API key vienen PRE-FLASHEADAS (registra el dispositivo en el
 * edge con POST /api/v1/iam/devices, copia el api_key devuelto y pegalo abajo).
 *
 * Librerias (Library Manager):
 *   - WiFiManager        (tzapu)
 *   - DHT sensor library (Adafruit) + Adafruit Unified Sensor
 *   - ArduinoJson v7     (bblanchon)
 *   ESPmDNS / WiFi / HTTPClient vienen con el core de ESP32.
 */

#include <WiFi.h>
#include <WiFiManager.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ===================== CONFIG (EDITAR) =====================
static const char* DEVICE_ID = "tracksilo-001";
static const char* API_KEY   = "test-api-key-123";   // <- pega aqui el api_key real del edge

static const char* EDGE_HOST     = "cafelab-edge";   // mDNS: cafelab-edge.local
static const uint16_t EDGE_PORT  = 5000;
static const char* EDGE_FALLBACK_IP = "";            // ej. "192.168.1.50" si mDNS falla

static const uint8_t DHT_PIN      = 4;               // dato del DHT22
static const uint8_t DHT_KIND     = DHT22;
static const uint8_t ACTUATOR_PIN = 2;               // LED on-board = deshumedecedor simulado

static const unsigned long READ_INTERVAL_MS = 30000; // 30 s (< 2 min => sensor ONLINE)
// ==========================================================

DHT dht(DHT_PIN, DHT_KIND);
IPAddress edgeIp;
unsigned long lastReadAt = 0;

IPAddress resolveEdge() {
  // Reintenta la resolucion mDNS unas pocas veces.
  for (int i = 0; i < 5; i++) {
    IPAddress ip = MDNS.queryHost(EDGE_HOST);
    if (ip != IPAddress(0, 0, 0, 0)) {
      return ip;
    }
    delay(500);
  }
  if (strlen(EDGE_FALLBACK_IP) > 0) {
    IPAddress ip;
    if (ip.fromString(EDGE_FALLBACK_IP)) {
      return ip;
    }
  }
  return IPAddress(0, 0, 0, 0);
}

void applyActuator(const String& command) {
  // El edge solo emite ACTIVATE / NONE.
  digitalWrite(ACTUATOR_PIN, command == "ACTIVATE" ? HIGH : LOW);
}

void sendReading(float temperature, float humidity) {
  if (edgeIp == IPAddress(0, 0, 0, 0)) {
    edgeIp = resolveEdge();
    if (edgeIp == IPAddress(0, 0, 0, 0)) {
      Serial.println("[edge] no se pudo resolver el edge (mDNS/fallback)");
      return;
    }
    Serial.print("[edge] encontrado en ");
    Serial.println(edgeIp);
  }

  String url = "http://" + edgeIp.toString() + ":" + String(EDGE_PORT) + "/api/v1/edge/readings";

  JsonDocument body;
  body["deviceId"] = DEVICE_ID;
  body["temperature"] = temperature;
  body["humidity"] = humidity;
  String payload;
  serializeJson(body, payload);

  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);

  int status = http.POST(payload);
  if (status > 0) {
    String response = http.getString();
    Serial.printf("[edge] %d %s\n", status, response.c_str());

    if (status == 200 || status == 201) {
      JsonDocument resp;
      if (deserializeJson(resp, response) == DeserializationError::Ok) {
        String command = resp["actuatorCommand"] | "NONE";
        applyActuator(command);
        Serial.printf("[actuador] %s\n", command.c_str());
      }
    } else if (status == 401) {
      Serial.println("[edge] 401: revisa DEVICE_ID / API_KEY");
    }
  } else {
    Serial.printf("[edge] POST fallo: %s\n", http.errorToString(status).c_str());
    edgeIp = IPAddress(0, 0, 0, 0);  // forzar re-resolucion la proxima vez
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(ACTUATOR_PIN, OUTPUT);
  digitalWrite(ACTUATOR_PIN, LOW);
  dht.begin();

  // WiFiManager: conecta con WiFi guardado, o abre el portal "TrackSilo-Setup".
  WiFiManager wm;
  if (!wm.autoConnect("TrackSilo-Setup")) {
    Serial.println("[wifi] fallo de conexion; reiniciando...");
    delay(3000);
    ESP.restart();
  }
  Serial.print("[wifi] conectado, IP ");
  Serial.println(WiFi.localIP());

  if (!MDNS.begin(DEVICE_ID)) {
    Serial.println("[mdns] no se pudo iniciar mDNS local");
  }
  edgeIp = resolveEdge();
  if (edgeIp != IPAddress(0, 0, 0, 0)) {
    Serial.print("[edge] resuelto en ");
    Serial.println(edgeIp);
  }
}

void loop() {
  unsigned long now = millis();
  if (now - lastReadAt < READ_INTERVAL_MS) {
    return;
  }
  lastReadAt = now;

  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature();
  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("[dht] lectura invalida");
    return;
  }

  Serial.printf("[dht] T=%.1fC H=%.1f%%\n", temperature, humidity);
  sendReading(temperature, humidity);
}
