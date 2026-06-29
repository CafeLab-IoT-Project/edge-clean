# Dashboard local del Edge

Este documento explica el dashboard local que corre dentro del servicio Flask del
edge. Es el dashboard de diagnostico de la Raspberry Pi, no el dashboard Angular
principal del backend/cloud.

## Endpoints

| Metodo | Endpoint | Para que sirve |
|---|---|---|
| `GET` | `/dashboard` | Devuelve la pagina HTML del dashboard local. |
| `GET` | `/api/v1/edge/dashboard` | Devuelve un snapshot JSON del estado actual. |
| `GET` | `/api/v1/edge/dashboard/stream` | Abre un stream SSE para actualizaciones en vivo. |

Los dos endpoints de datos aceptan `?deviceId=<id>`.

Ejemplos:

```bash
curl http://raspberrypi.local:5000/dashboard
curl http://raspberrypi.local:5000/api/v1/edge/dashboard
curl "http://raspberrypi.local:5000/api/v1/edge/dashboard?deviceId=esp32-aabbccddeeff"
```

## Que muestra

El dashboard muestra solo dispositivos ya asignados a un lote (`lot_id != null`).
Si no hay dispositivos asignados, muestra el mensaje para ir a `/onboarding`.

El snapshot contiene:

```json
{
  "hasDevice": true,
  "deviceId": "esp32-aabbccddeeff",
  "lotId": "7",
  "connectionStatus": "ONLINE",
  "lastSeenAt": "2026-06-29T20:10:00Z",
  "reading": {
    "readingId": 12,
    "temperature": 21.4,
    "humidity": 58.0,
    "status": "OPTIMAL",
    "actuatorCommand": "NONE",
    "humidityAlert": false,
    "temperatureAlert": false,
    "recordedAt": "2026-06-29T20:10:00Z"
  },
  "thresholds": {
    "minTemperature": 18.0,
    "maxTemperature": 22.0,
    "minHumidity": 55.0,
    "maxHumidity": 65.0
  }
}
```

Si no se manda `deviceId`, el dashboard selecciona el dispositivo asignado con la
lectura mas reciente. Si se manda `deviceId`, intenta mostrar ese dispositivo; si
no existe o no esta asignado, vuelve al mas reciente.

## Como funciona el SSE

La pagina `/dashboard` usa JavaScript nativo:

```js
new EventSource('/api/v1/edge/dashboard/stream' + location.search)
```

El endpoint `/api/v1/edge/dashboard/stream` mantiene una conexion HTTP abierta
con `Content-Type: text/event-stream`. Al conectarse envia un snapshot inicial.
Luego escucha eventos internos del edge y envia mensajes SSE:

```text
data: {"kind":"snapshot","snapshot":{...}}

data: {"kind":"flow","flow":{...}}

: keepalive
```

Tipos de mensaje:

| `kind` | Cuando aparece | Que actualiza |
|---|---|---|
| `snapshot` | Al abrir el stream, al llegar una lectura o al cambiar umbrales | Tarjetas de temperatura/humedad, estado, umbrales, conexion |
| `flow` | En cada request trazado del edge o del backend | Paneles laterales de flujo |
| `keepalive` | Cada 15 s sin eventos | Mantiene viva la conexion SSE |

Flask debe correr con `threaded=True` porque el stream SSE deja una conexion
abierta; sin hilos podria bloquear otros requests.

## Donde esta conectado

El dashboard se conecta a un bus de eventos en memoria:

```text
ESP32/UI -> Flask endpoint -> EventBus -> SSE stream -> Browser dashboard
SyncWorker -> BackendClient -> EventBus -> SSE stream -> Browser dashboard
```

Eventos principales:

| Evento | Quien lo publica | Para que sirve |
|---|---|---|
| `READING` | `POST /api/v1/edge/readings` | Fuerza un nuevo snapshot con la ultima lectura. |
| `THRESHOLDS` | `PUT /api/v1/edge/thresholds` y sync de umbrales | Fuerza un nuevo snapshot y anima los umbrales. |
| `FLOW` | `app.py` y `BackendClient` | Muestra requests en los paneles laterales. |

Detalles importantes:

- `FLOW` del lado izquierdo registra requests que entran a endpoints
  `/api/v1/edge/*` y `/api/v1/iam/*`.
- `FLOW` del lado derecho registra llamadas salientes al backend Java
  (`sign-in`, `telemetry-records`, `environment-thresholds`, etc.).
- Las rutas del propio dashboard se excluyen del tracing para no generar ruido ni
  loops visuales.
- El bus redacta credenciales (`api_key`, `X-API-Key`, `password`, `token`,
  `Authorization`) antes de enviarlas al navegador.

## Arquitectura

El dashboard respeta la arquitectura por capas del edge:

| Capa | Archivo | Responsabilidad |
|---|---|---|
| Interface | `iotmonitoring/interfaces/dashboard_services.py` | Blueprint Flask, endpoints `/dashboard`, snapshot JSON y SSE. |
| Interface | `iotmonitoring/interfaces/services.py` | Endpoints de lecturas/umbrales que publican `READING` y `THRESHOLDS`. |
| Interface | `app.py` | Registra blueprints y publica `FLOW` de requests entrantes. |
| Application | `iotmonitoring/application/services.py` | Calcula lectura actual, estado, alertas y sensor `ONLINE/OFFLINE`. |
| Application | `iotmonitoring/application/sync_services.py` | Baja umbrales del backend y publica `THRESHOLDS` si cambiaron. |
| Infrastructure | `iotmonitoring/infrastructure/repositories.py` | Lee dispositivos, lecturas y umbrales desde SQLite. |
| Infrastructure | `iotmonitoring/infrastructure/backend_client.py` | Llama al backend y publica `FLOW` del lado derecho. |
| Shared | `shared/infrastructure/events.py` | Event bus in-memory, colas por suscriptor y redaccion de secretos. |
| Shared | `shared/infrastructure/sync_worker.py` | Worker de sync que empuja lecturas y baja umbrales en segundo plano. |

El dashboard no guarda estado propio en base de datos. Cada snapshot se recalcula
leyendo el estado actual de SQLite mediante servicios/repositorios.

## Flujo completo de una lectura

1. El ESP32 envia `POST /api/v1/edge/readings` con `deviceId`, temperatura,
   humedad y `X-API-Key`.
2. `iotmonitoring/interfaces/services.py` autentica, guarda la lectura y calcula
   `status`, `actuatorCommand`, `humidityAlert` y `temperatureAlert`.
3. El endpoint llama a `sync_worker.notify()` para despertar el push al backend.
4. El endpoint publica `READING` en el `EventBus`.
5. El stream SSE recibe `READING` y manda un nuevo `snapshot`.
6. El browser actualiza las tarjetas de temperatura/humedad y anima los valores.
7. En paralelo, `app.py` publica `FLOW` para mostrar el request en el panel
   "Entrada al edge".
8. Si el worker llama al backend, `backend_client.py` publica `FLOW` para el
   panel "Sync worker".

## Archivos clave

- `iotmonitoring/interfaces/dashboard_services.py`
- `shared/infrastructure/events.py`
- `app.py`
- `iotmonitoring/interfaces/services.py`
- `iotmonitoring/application/services.py`
- `iotmonitoring/application/sync_services.py`
- `iotmonitoring/infrastructure/backend_client.py`
- `shared/infrastructure/sync_worker.py`
- `iotmonitoring/interfaces/account_services.py` (`/onboarding`, asignacion de lotes)

## Limitaciones actuales

- No tiene autenticacion; esta pensado para la LAN/local del edge.
- El bus es in-memory; si el proceso Flask reinicia, se pierden eventos en vivo.
- El SSE esta pensado para un proceso Flask. Con multiples procesos, cada proceso
  tendria su propio bus.
- Las asignaciones hechas en `/onboarding` generan `FLOW`, pero el snapshot se
  refresca automaticamente al llegar una nueva lectura o cambio de umbrales.
