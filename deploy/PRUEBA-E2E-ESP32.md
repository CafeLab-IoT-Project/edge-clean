# Prueba E2E: ESP32 (real) → Edge (Pi) → Backend

Guía para validar el flujo completo con el ESP32 físico, el edge corriendo en la
Raspberry Pi (`raspberrypi.local:5000`) y el backend Java.

> **Placeholders**
> - `<PI>` = `raspberrypi.local` (o la IP del Pi si mDNS no resuelve).
> - `<BACKEND>` = `IP:8080` del backend (p. ej. `192.168.1.20:8080`). **Aún no
>   deployado** — complétalo cuando lo tengas.
> - `<LOT_ID>` = el `coffeeLotId` que exista en el backend (en la prueba previa = `1`).

---

## Mapa del flujo

```
ESP32 ──POST /api/v1/edge/readings (X-API-Key)──► EDGE (Pi:5000)
                                                    │  guarda en SQLite (outbox, is_synced=0)
                                                    │  evalúa umbral → responde actuatorCommand
                                                    ▼
                              SyncWorker (auto) ó POST /api/v1/edge/sync
                                                    │
                              POST /api/v1/telemetry-records (Bearer JWT) ──► BACKEND
```

Dos saltos independientes:
1. **ESP32 → edge**: autentica con `device_id` + `X-API-Key` (credenciales del
   dispositivo, locales al edge).
2. **Edge → backend**: autentica con el JWT de la **cuenta** onboardeada
   (`POST /api/v1/edge/account`). El puente de identidad es
   `device.lot_id` = `coffeeLotId` del backend.

---

## Pre-requisitos

### a) El edge está vinculado a una cuenta
```bash
curl http://<PI>:5000/api/v1/edge/account
# espera: {"configured": true, "baseUrl": "...", "email": "..."}
```
Si sale `configured:false`, onboardea primero:
```bash
curl -X POST http://<PI>:5000/api/v1/edge/account \
  -H "Content-Type: application/json" \
  -d '{"baseUrl":"http://<BACKEND>","email":"dueno@cafelab.com","password":"TU_PASS"}'
```

### b) Existe un coffee-lot en el backend
Anota su `coffeeLotId` → ese es `<LOT_ID>`. El `lot_id` que le pongas al
dispositivo **debe existir en el backend**, o el push fallará con 4xx y el edge
descartará esas lecturas.

---

## Paso 0 — IP del Pi y health check (desde la laptop)
```bash
ping raspberrypi.local
curl http://<PI>:5000/health
```

---

## Paso 1 — Flashear el ESP32 (firmware genérico, UNA sola vez)

Ya **no se hornea** `device_id` ni `api_key`: el `device_id` es la MAC y el
`api_key` lo obtiene solo (auto-enroll). En
`firmware/tracksilo-esp32/tracksilo-esp32.ino`, bloque CONFIG:
```cpp
static const char* DEVICE_ID_OVERRIDE = "";              // vacío = usar la MAC
static const char* EDGE_SERVICE     = "cafelab";         // descubrimiento por _cafelab._tcp
static const char* EDGE_HOST        = "raspberrypi";     // hostname mDNS (respaldo)
static const char* EDGE_FALLBACK_IP = "<PI_IP>";         // respaldo si mDNS falla
```
Librerías (Library Manager): **WiFiManager** (tzapu), **DHT sensor library**
(Adafruit) + **Adafruit Unified Sensor**, **ArduinoJson v7** (`Preferences` y
`ESPmDNS` vienen con el core). Sube el sketch.

> Para que el descubrimiento por servicio funcione, instala el servicio Avahi en
> el Pi (ver `deploy/raspberrypi/edge-discovery.md`).

---

## Paso 2 — WiFi + auto-enroll (phone-home)

Al arrancar sin WiFi → AP **`TrackSilo-Setup`** → conéctate, elige la WiFi (la
**misma del Pi**). Monitor Serie (115200) — esperado:
```
[wifi] conectado, IP 192.168.18.x
[id] deviceId = esp32-aabbccddeeff
[mdns] edge por servicio 'cafelab': 192.168.18.129:5000 (raspberrypi)
[announce] ok; PENDIENTE: asigna un lote en /onboarding
[dht] T=21.3C H=58.0%  ->  201 status=... actuador=...
```
- El ESP32 **se anunció solo** → aparece como **pendiente** en la web.
- `[mdns] usando IP fija ...` → el mDNS falló, pero la IP de respaldo lo cubre.
- El `api_key` queda guardado en NVS; no lo escribes en ningún lado.

---

## Paso 3 — Asignar el lote desde la web

`/onboarding` → **Dispositivos detectados** → **Actualizar** → el `esp32-<mac>`
aparece **pendiente** → elige el lote en el dropdown → **Asignar**.

O por curl (sustituye el `device_id` real que viste en el serial):
```bash
curl -X POST http://<PI>:5000/api/v1/edge/devices/esp32-aabbccddeeff/assign \
  -H "Content-Type: application/json" -d '{"lotId":"<LOT_ID>"}'
```
Hasta que tenga lote, el edge **bufferea** las lecturas (responde al actuador con
umbrales por defecto) pero **no** las sincroniza al backend.

---

## Paso 4 — Verificar la lectura EN EL EDGE (desde la laptop)
```bash
curl "http://<PI>:5000/api/v1/edge/readings/latest?deviceId=esp32-aabbccddeeff"
```
```json
{"readingId":12,"deviceId":"esp32-aabbccddeeff","temperature":21.3,"humidity":58.0,
 "status":"OPTIMAL","actuatorCommand":"NONE","recordedAt":"2026-..Z"}
```
Confirma el salto **ESP32 → edge**. ✅

---

## Paso 5 — Empujar al BACKEND y verificar

El `SyncWorker` empuja solo, pero para **forzarlo ahora** necesitas el `api_key`
del device (auth). Recupéralo re-anunciando (es idempotente):
```bash
curl -X POST http://<PI>:5000/api/v1/iam/devices/announce \
  -H "Content-Type: application/json" -d '{"deviceId":"esp32-aabbccddeeff"}'
# -> {"api_key":"AbC123...","assigned":true,...}
```
Luego fuerza el sync (`device_id` en el body + `X-API-Key`):
```bash
curl -X POST http://<PI>:5000/api/v1/edge/sync \
  -H "Content-Type: application/json" \
  -H "X-API-Key: AbC123..." \
  -d '{"device_id":"esp32-aabbccddeeff"}'
```
```json
{"readingsPushed": 3, "readingsSkipped": 0, "thresholdsUpdated": 1}
```
- `readingsPushed` > 0 → el edge mandó las lecturas al backend. ✅
- `readingsSkipped` > 0 → el backend rechazó (típicamente `<LOT_ID>` no existe allá).

**Confirmar en el backend** (necesita JWT de la cuenta):
```bash
# 1) sign-in → token
curl -X POST http://<BACKEND>/api/v1/authentication/sign-in \
  -H "Content-Type: application/json" \
  -d '{"email":"dueno@cafelab.com","password":"TU_PASS"}'

# 2) ver la telemetría del lote
curl http://<BACKEND>/api/v1/telemetry-records/coffee-lot/<LOT_ID> \
  -H "Authorization: Bearer <TOKEN>"
```
Deberías ver las lecturas reales del ESP32. Cierra el salto **edge → backend**. ✅

---

## Resumen de endpoints

| # | Quién llama | Método + endpoint | Auth | Para qué |
|---|---|---|---|---|
| 1 | ESP32 (auto) | `POST /api/v1/iam/devices/announce` | — | auto-enroll; emite/recupera `api_key` |
| 2 | Tú (web) | `POST /api/v1/edge/devices/{id}/assign` | — | asignar lote al device |
| 3 | ESP32 | `POST /api/v1/edge/readings` | `X-API-Key` + deviceId | enviar lectura |
| 4 | Tú (check) | `GET /api/v1/edge/readings/latest` | — | ver última lectura en el edge |
| 5 | Tú (push) | `POST /api/v1/edge/sync` | `X-API-Key` + deviceId | forzar envío al backend |
| 6 | Tú (check) | `GET /api/v1/telemetry-records/coffee-lot/{id}` | `Bearer JWT` | ver dato en el backend |

---

## Checklist antes de empezar
- [ ] Backend deployado y alcanzable desde el Pi (`<BACKEND>`).
- [ ] `baseUrl` onboardeado en el edge apunta a ese backend.
- [ ] Existe un coffee-lot → `<LOT_ID>` anotado.
- [ ] Pi, ESP32 y laptop en la **misma red WiFi**.
- [ ] Recompilar el jar del backend incluyendo `monitoring` (ver HALLAZGOS.md #2).
