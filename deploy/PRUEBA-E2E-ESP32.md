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

## Paso 1 — Registrar el dispositivo en el EDGE → obtener su API key

Sin auth (es el alta). Devuelve el `api_key` a flashear.
```bash
curl -X POST http://<PI>:5000/api/v1/iam/devices \
  -H "Content-Type: application/json" \
  -d '{"device_id":"tracksilo-001","lot_id":"<LOT_ID>"}'
```
Respuesta (201):
```json
{
  "device_id": "tracksilo-001",
  "lot_id": "<LOT_ID>",
  "api_key": "AbC123...",
  "created_at": "2026-..Z"
}
```
- `device_id`: nombre único del ESP32 (lo eliges tú).
- `lot_id`: el coffeeLotId del backend (pre-req b).
- Si ya existe → 409. Usa otro `device_id` o reutiliza el api_key previo.

---

## Paso 2 — Flashear el ESP32

En `firmware/tracksilo-esp32/tracksilo-esp32.ino`, edita el bloque CONFIG:
```cpp
static const char* DEVICE_ID = "tracksilo-001";        // mismo del paso 1
static const char* API_KEY   = "AbC123...";            // api_key del paso 1

static const char* EDGE_HOST     = "raspberrypi";      // ⚠️ hostname del Pi = raspberrypi, NO cafelab-edge
static const uint16_t EDGE_PORT  = 5000;
static const char* EDGE_FALLBACK_IP = "<PI_IP>";       // IP del Pi por si mDNS falla (recomendado)
```
> **Hallazgo #8**: el firmware busca `cafelab-edge.local` por defecto, pero el
> hostname del Pi quedó como `raspberrypi`. Cambia `EDGE_HOST` a `"raspberrypi"`
> **y** pon `EDGE_FALLBACK_IP` con la IP.

Librerías (Library Manager): **WiFiManager** (tzapu), **DHT sensor library**
(Adafruit) + **Adafruit Unified Sensor**, **ArduinoJson v7**. Sube el sketch.

---

## Paso 3 — Conectar el ESP32 a la WiFi (portal del ESP32)

Al arrancar sin WiFi guardado abre el AP **`TrackSilo-Setup`**:
1. Conéctate a `TrackSilo-Setup` con el celular/laptop.
2. Portal cautivo → elige tu red WiFi (la **misma del Pi**) → clave.
3. El ESP32 se reinicia y conecta.

Monitor Serie (115200 baudios) — esperado:
```
[wifi] conectado, IP 192.168.1.x
[edge] encontrado en 192.168.1.50
[dht] T=21.3C H=58.0%
[edge] 201 {"readingId":..,"status":"OPTIMAL","actuatorCommand":"NONE",...}
[actuador] NONE
```
- Manda una lectura cada 30 s (`READ_INTERVAL_MS`).
- `401: revisa DEVICE_ID / API_KEY` → no coinciden con el paso 1.
- `POST fallo` → no alcanza el edge (misma red? IP/hostname correctos?).

Lo que manda el firmware:
```
POST http://<PI>:5000/api/v1/edge/readings
Header: X-API-Key: AbC123...
Body: {"deviceId":"tracksilo-001","temperature":21.3,"humidity":58.0}
```

---

## Paso 4 — Verificar la lectura EN EL EDGE (desde la laptop)
```bash
curl "http://<PI>:5000/api/v1/edge/readings/latest?deviceId=tracksilo-001"
```
```json
{"readingId":12,"deviceId":"tracksilo-001","temperature":21.3,"humidity":58.0,
 "status":"OPTIMAL","actuatorCommand":"NONE","recordedAt":"2026-..Z"}
```
Confirma el salto **ESP32 → edge**. ✅

---

## Paso 5 — Empujar al BACKEND y verificar

El `SyncWorker` empuja solo, pero para **forzarlo ahora** (auth de dispositivo:
`device_id` en el body + `X-API-Key`):
```bash
curl -X POST http://<PI>:5000/api/v1/edge/sync \
  -H "Content-Type: application/json" \
  -H "X-API-Key: AbC123..." \
  -d '{"device_id":"tracksilo-001"}'
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
| 1 | Tú (alta) | `POST /api/v1/iam/devices` | — | registrar device, obtener `api_key` |
| 2 | ESP32 | `POST /api/v1/edge/readings` | `X-API-Key` + deviceId | enviar lectura |
| 3 | Tú (check) | `GET /api/v1/edge/readings/latest` | — | ver última lectura en el edge |
| 4 | Tú (push) | `POST /api/v1/edge/sync` | `X-API-Key` + deviceId | forzar envío al backend |
| 5 | Tú (check) | `GET /api/v1/telemetry-records/coffee-lot/{id}` | `Bearer JWT` | ver dato en el backend |

---

## Checklist antes de empezar
- [ ] Backend deployado y alcanzable desde el Pi (`<BACKEND>`).
- [ ] `baseUrl` onboardeado en el edge apunta a ese backend.
- [ ] Existe un coffee-lot → `<LOT_ID>` anotado.
- [ ] Pi, ESP32 y laptop en la **misma red WiFi**.
- [ ] Recompilar el jar del backend incluyendo `monitoring` (ver HALLAZGOS.md #2).
