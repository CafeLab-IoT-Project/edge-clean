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
  - ESPmDNS / WiFi / HTTPClient vienen con el core ESP32.

## Antes de flashear: obtener la API key

El edge **genera** la API key. Regístralo una vez y copia el `api_key`:

```powershell
Invoke-RestMethod `
  -Uri "http://cafelab-edge.local:5000/api/v1/iam/devices" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{ "deviceId": "tracksilo-001", "lotId": "7" }'
```

> En desarrollo ya existe `tracksilo-001` / `test-api-key-123` (sembrado por el
> edge), así que puedes flashear con esos valores directamente.

Edita en `tracksilo-esp32.ino` la sección **CONFIG**:

```cpp
static const char* DEVICE_ID = "tracksilo-001";
static const char* API_KEY   = "<pega-aqui-el-api_key>";
```

`lotId` es el `coffeeLotId` del backend; deja que lo gestione el edge (no va en
el firmware).

## Flashear

1. Conecta el ESP32 por USB y selecciona la placa (ej. "ESP32 Dev Module") y el
   puerto COM correctos.
2. Sube el sketch (Upload).
3. Abre el Monitor Serie a **115200 baudios**.

## Primer arranque (provisioning de WiFi)

1. Al no tener WiFi guardado, el ESP32 emite el AP **`TrackSilo-Setup`**.
2. Conéctate desde el celular → se abre el portal → elige la red del café y la
   clave.
3. El ESP32 se reconecta, resuelve `cafelab-edge.local` por mDNS y empieza a
   enviar lecturas cada 30 s.

En el Monitor Serie deberías ver algo como:

```
[wifi] conectado, IP 192.168.1.42
[edge] encontrado en 192.168.1.50
[dht] T=21.4C H=58.0%
[edge] 201 {"status":"OPTIMAL","actuatorCommand":"NONE",...}
[actuador] NONE
```

## Notas

- Si mDNS no funciona en tu red, define `EDGE_FALLBACK_IP` con la IP fija del Pi.
- El intervalo de 30 s mantiene el sensor como `ONLINE` (el edge marca `OFFLINE`
  tras 2 min sin lecturas).
- El edge solo emite `ACTIVATE` / `NONE`; el firmware enciende el actuador con
  `ACTIVATE` y lo apaga en cualquier otro caso.
- Pre-flasheo de la key = simple para demo. La alternativa (pairing automático:
  el ESP32 llama `POST /iam/devices` y guarda la key en NVS) queda como mejora.
