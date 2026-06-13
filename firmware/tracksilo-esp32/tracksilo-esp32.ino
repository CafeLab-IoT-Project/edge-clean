/*
 * TrackSilo - Firmware del sensor ESP32 + DHT22 para CafeLab.
 *
 * Firmware GENÉRICO: se flashea igual en todos los dispositivos, sin hornear
 * credenciales. El device_id se deriva de la MAC y la api_key se obtiene en
 * runtime (auto-enrollment) y se guarda en NVS. NO hay que reflashear por
 * dispositivo ni configurar el lote aquí: el lote se asigna desde la web
 * /onboarding del edge.
 *
 * Flujo:
 *   1. WiFiManager: si no hay WiFi guardado, abre el AP "TrackSilo-Setup" con
 *      portal cautivo para que el usuario ingrese la red del cafe.
 *   2. mDNS: resuelve el edge en "cafelab-edge.local" (sin IP fija).
 *   3. Announce (phone-home): POST /api/v1/iam/devices/announce {deviceId:MAC}
 *      -> el edge devuelve la api_key, que se guarda en NVS (Preferences).
 *   4. Loop: lee el DHT22 y hace POST /api/v1/edge/readings con la api_key.
 *      Aplica el actuatorCommand de la respuesta. Si recibe 401 (p.ej. el edge
 *      fue reseteado), borra la key y se vuelve a anunciar.
 *
 * Librerias (Library Manager):
 *   - WiFiManager        (tzapu)
 *   - DHT sensor library (Adafruit) + Adafruit Unified Sensor
 *   - ArduinoJson v7     (bblanchon)
 *   ESPmDNS / WiFi / HTTPClient / Preferences vienen con el core de ESP32.
 */

#include <WiFi.h>
#include <WiFiManager.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <DHT.h>

// ===================== CONFIG (igual para todos los dispositivos) =====================
static const char* DEVICE_PREFIX = "esp32-";        // device_id = esp32-<mac>

static const char* EDGE_HOST     = "cafelab-edge";   // mDNS: cafelab-edge.local
static const uint16_t EDGE_PORT  = 5000;
static const char* EDGE_FALLBACK_IP = "";            // ej. "192.168.18.129" si mDNS falla

static const uint8_t DHT_PIN      = 4;               // dato del DHT22
static const uint8_t DHT_KIND     = DHT22;
static const uint8_t ACTUATOR_PIN = 2;               // LED on-board = deshumedecedor simulado

static const unsigned long READ_INTERVAL_MS = 30000; // 30 s (< 2 min => sensor ONLINE)
// =====================================================================================

DHT dht(DHT_PIN, DHT_KIND);
Preferences prefs;
IPAddress edgeIp;
String deviceId;
String apiKey;
unsigned long lastReadAt = 0;

String computeDeviceId() {
  String mac = WiFi.macAddress();   // formato AA:BB:CC:DD:EE:FF
  mac.replace(":", "");
  mac.toLowerCase();
  return String(DEVICE_PREFIX) + mac;
}

IPAddress resolveEdge() {
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

String edgeUrl(const String& path) {
  return "http://" + edgeIp.toString() + ":" + String(EDGE_PORT) + path;
}

// Phone-home: se anuncia al edge y obtiene (y persiste) su api_key.
bool announce() {
  if (edgeIp == IPAddress(0, 0, 0, 0)) {
    edgeIp = resolveEdge();
    if (edgeIp == IPAddress(0, 0, 0, 0)) {
      Serial.println("[announce] no se pudo resolver el edge");
      return false;
    }
  }

  JsonDocument body;
  body["deviceId"] = deviceId;
  String payload;
  serializeJson(body, payload);

  HTTPClient http;
  http.begin(edgeUrl("/api/v1/iam/devices/announce"));
  http.addHeader("Content-Type", "application/json");
  int status = http.POST(payload);
  bool ok = false;

  if (status == 200) {
    JsonDocument resp;
    if (deserializeJson(resp, http.getString()) == DeserializationError::Ok) {
      apiKey = String((const char*)(resp["api_key"] | ""));
      if (apiKey.length() > 0) {
        prefs.putString("apiKey", apiKey);
        bool assigned = resp["assigned"] | false;
        Serial.printf("[announce] ok; %s\n",
          assigned ? "con lote" : "PENDIENTE: asigna un lote en /onboarding");
        ok = true;
      }
    }
  } else {
    Serial.printf("[announce] fallo %d: %s\n", status, http.getString().c_str());
  }
  http.end();
  return ok;
}

void applyActuator(const String& command) {
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

  if (apiKey.length() == 0 && !announce()) {
    return;  // sin api_key no se puede autenticar
  }

  JsonDocument body;
  body["deviceId"] = deviceId;
  body["temperature"] = temperature;
  body["humidity"] = humidity;
  String payload;
  serializeJson(body, payload);

  HTTPClient http;
  http.begin(edgeUrl("/api/v1/edge/readings"));
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", apiKey);

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
      // El edge no reconoce la key (p.ej. fue reseteado): re-anunciarse.
      Serial.println("[edge] 401: re-anunciando para obtener nueva api_key");
      apiKey = "";
      prefs.remove("apiKey");
      announce();
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

  deviceId = computeDeviceId();
  Serial.print("[id] deviceId = ");
  Serial.println(deviceId);

  prefs.begin("tracksilo", false);
  apiKey = prefs.getString("apiKey", "");

  if (!MDNS.begin(deviceId.c_str())) {
    Serial.println("[mdns] no se pudo iniciar mDNS local");
  }
  edgeIp = resolveEdge();
  if (edgeIp != IPAddress(0, 0, 0, 0)) {
    Serial.print("[edge] resuelto en ");
    Serial.println(edgeIp);
  }

  // Si no tenemos api_key guardada, anunciarse para obtenerla.
  if (apiKey.length() == 0) {
    announce();
  } else {
    Serial.println("[id] api_key recuperada de NVS");
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
