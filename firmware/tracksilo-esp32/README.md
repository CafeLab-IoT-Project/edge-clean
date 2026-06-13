# Firmware TrackSilo (ESP32 + DHT22)

Sensor que envía lecturas de temperatura/humedad al edge y acciona el
deshumedecedor (LED en la versión académica) según la respuesta del edge.

## Hardware

| Componente | Pin ESP32 (por defecto) |
|---|---|
| DHT22 (dato) | GPIO 4 |
| Actuador / LED on-board | GPIO 2 |

DHT22: VCC a 3V3, GND a GND, DATA a GPIO 4 (resistencia pull-up de 10k entre
DATA y VCC si tu módulo no la trae).

## Requisitos de software

- **Arduino IDE** con el core de **ESP32** instalado
  (Boards Manager → "esp32" by Espressif).
- Librerías (Library Manager):
  - WiFiManager (tzapu)
  - DHT sensor library (Adafruit) + Adafruit Unified Sensor
  - ArduinoJson **v7** (bblanchon)
  - ESPmDNS / WiFi / HTTPClient / **Preferences** vienen con el core ESP32.

## Sin reflasheo: firmware genérico (auto-enroll)

El mismo firmware se flashea **igual en todos los dispositivos**. NO se hornea
`device_id` ni `api_key`:

- `device_id` = `esp32-<MAC>` automáticamente.
- En el primer arranque el ESP32 se **anuncia** al edge
  (`POST /api/v1/iam/devices/announce`) y recibe su `api_key`, que guarda en
  **NVS**. Se reusa en cada arranque y se renueva solo (re-announce) si el edge
  responde 401 (p. ej. tras un reset).
- El **lote** ya no va en el firmware: se asigna desde la web `/onboarding`.

Edita solo la sección **CONFIG** si hace falta (descubrimiento del edge):

```cpp
static const char* DEVICE_ID_OVERRIDE = "";              // vacío = usar la MAC; fija un id para simular otro IoT
static const char* EDGE_SERVICE     = "cafelab";         // descubrimiento por _cafelab._tcp (preferido)
static const char* EDGE_HOST        = "raspberrypi";     // hostname mDNS (respaldo)
static const char* EDGE_FALLBACK_IP = "192.168.18.129";  // respaldo si mDNS falla (vacío = solo-mDNS)
```

> Para el descubrimiento por servicio, instala el servicio Avahi en el Pi
> (`deploy/raspberrypi/edge-discovery.md`).

## Flashear

1. Conecta el ESP32 por USB y selecciona la placa (ej. "ESP32 Dev Module") y el
   puerto COM correctos.
2. Sube el sketch (Upload).
3. Abre el Monitor Serie a **115200 baudios**.

## Primer arranque (WiFi + auto-enroll)

1. Al no tener WiFi guardado, el ESP32 emite el AP **`TrackSilo-Setup`**.
2. Conéctate desde el celular → portal → elige la red del café y la clave.
3. El ESP32 se reconecta, **descubre el edge** (servicio mDNS → host → IP fija),
   **se anuncia** y empieza a enviar lecturas cada 30 s.
4. En la web `/onboarding`, **asígnale un lote** (aparece como "pendiente").

En el Monitor Serie deberías ver algo como:

```
[wifi] conectado, IP 192.168.18.42
[id] deviceId = esp32-aabbccddeeff
[mdns] edge por servicio 'cafelab': 192.168.18.129:5000 (raspberrypi)
[announce] ok; PENDIENTE: asigna un lote en /onboarding
[dht] T=21.4C H=58.0%
[edge] 201 {"status":"OPTIMAL","actuatorCommand":"NONE",...}
[actuador] NONE
```

## Notas

- El log dice qué método de descubrimiento funcionó: `por servicio` / `por host`
  / `usando IP fija`. Si mDNS falla, la IP de respaldo lo cubre.
- El intervalo de 30 s mantiene el sensor como `ONLINE` (el edge marca `OFFLINE`
  tras 2 min sin lecturas).
- El edge solo emite `ACTIVATE` / `NONE`; el firmware enciende el actuador con
  `ACTIVATE` (solo reacciona a **humedad** alta) y lo apaga en cualquier otro caso.
- Para simular varios IoT en una placa de pruebas, usa `DEVICE_ID_OVERRIDE`.
