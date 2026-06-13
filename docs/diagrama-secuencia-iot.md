# Diagrama de secuencia — CafeLab IoT (registro → umbrales → telemetría)

Cubre el ciclo de vida completo: registro del dispositivo IoT en el edge,
vinculación del edge a la cuenta del backend, configuración de umbrales por el
usuario, envío de lecturas (device → edge, local e instantáneo) y la
sincronización en segundo plano (edge ↔ backend) que sube telemetría y baja
umbrales.

## Participantes

| Participante | Qué es | Repo |
|---|---|---|
| **Operador** | Persona que provisiona el hardware y vincula la cuenta | — |
| **Usuario CafeLab** | Dueño del lote; configura umbrales desde la app/web | — |
| **ESP32** | Firmware TrackSilo (DHT22 + actuador) | `edge-clean/firmware/tracksilo-esp32` |
| **Edge** | Servicio Flask en la Raspberry Pi (SQLite local) | `edge-clean` |
| **Sync Worker** | Hilo daemon dentro del Edge (cada 30 s) | `edge-clean/shared/infrastructure/sync_worker.py` |
| **Backend** | API Spring Boot CafeLab (JWT) | `cafeLab-backEnd` |

> Nota de vínculo de datos: en el Edge el dispositivo se registra con un
> `lot_id`. Ese `lot_id` **es** el `coffeeLotId` del backend (debe ser
> numérico); así el Edge sabe a qué lote subir telemetría y de qué lote bajar
> umbrales (`_coffee_lot_id_for` en `sync_services.py`).

---

## Diagrama

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontSize": "14px",
    "primaryColor": "#ffffff",
    "primaryTextColor": "#1a1a1a",
    "primaryBorderColor": "#5b6b7a",
    "lineColor": "#333333",
    "actorBkg": "#e8eef7",
    "actorBorder": "#5b6b7a",
    "actorTextColor": "#1a1a1a",
    "signalColor": "#333333",
    "signalTextColor": "#111111",
    "noteBkgColor": "#fff3c4",
    "noteTextColor": "#1a1a1a",
    "noteBorderColor": "#d4b106",
    "sequenceNumberColor": "#ffffff",
    "labelBoxBkgColor": "#f2f4f7",
    "labelTextColor": "#1a1a1a"
  }
}}%%
sequenceDiagram
    autonumber
    actor Op as Operador
    actor User as Usuario CafeLab
    participant ESP as ESP32 (TrackSilo)
    participant Edge as Edge (Flask / Pi)
    participant Worker as Sync Worker (Edge)
    participant BE as Backend (Spring / JWT)

    %% ============ FASE 0: prerequisito en el backend ============
    rect rgb(235, 245, 255)
    note over User,BE: FASE 0 — El usuario ya tiene un lote de café en el backend
    User->>BE: POST /api/v1/authentication/sign-in {email, password}
    BE-->>User: 200 {id, email, role, token}
    User->>BE: POST /api/v1/coffee-lots {...} (Bearer token)
    BE-->>User: 201 {id: coffeeLotId, ...}
    note right of User: Anota coffeeLotId — será el lot_id del IoT
    end

    %% ============ FASE 1: registro del IoT en el edge ============
    rect rgb(240, 255, 240)
    note over Op,Edge: FASE 1 — Registro del dispositivo IoT (provisioning)
    Op->>Edge: POST /api/v1/iam/devices {device_id:"tracksilo-001", lot_id:"<coffeeLotId>"}
    Edge->>Edge: Genera api_key, persiste Device en SQLite
    Edge-->>Op: 201 {device_id, lot_id, api_key, created_at}
    note right of Op: Copia api_key y device_id al firmware
    Op->>ESP: Flashea DEVICE_ID + API_KEY (pre-flasheado)
    end

    %% ============ FASE 2: vincular el edge a la cuenta del backend ============
    rect rgb(255, 250, 235)
    note over Op,BE: FASE 2 — Vincular el edge a la cuenta (onboarding)
    Op->>Edge: GET /onboarding (formulario web)
    Op->>Edge: POST /api/v1/edge/account {email, password, backendUrl}
    Edge->>BE: POST /api/v1/authentication/sign-in {email, password}
    alt Credenciales válidas
        BE-->>Edge: 200 {token}
        Edge->>Edge: Guarda cuenta (BackendAccountRepository) + arranca Sync Worker
        Edge-->>Op: 200 {configured:true, email, backendUrl}
    else Inválidas / backend caído
        BE-->>Edge: 404 / error de red
        Edge-->>Op: 401 "Credenciales inválidas" / 502 "backend no disponible"
    end
    end

    %% ============ FASE 3: arranque del ESP32 ============
    rect rgb(245, 240, 255)
    note over ESP,Edge: FASE 3 — Arranque del sensor
    ESP->>ESP: WiFiManager (portal "TrackSilo-Setup" si no hay WiFi)
    ESP->>Edge: mDNS query "cafelab-edge.local"
    Edge-->>ESP: IP del edge (o IP de fallback)
    end

    %% ============ FASE 4: envío de lecturas (local, instantáneo) ============
    rect rgb(255, 240, 245)
    note over ESP,Edge: FASE 4 — Lectura cada 30 s (camino device→edge, siempre local)
    loop cada READ_INTERVAL_MS (30 s)
        ESP->>ESP: Lee DHT22 (temperature, humidity)
        ESP->>Edge: POST /api/v1/edge/readings\nX-API-Key: <api_key>\n{deviceId, temperature, humidity}
        Edge->>Edge: Autentica (device_id + X-API-Key)
        Edge->>Edge: Guarda reading (unsynced) + evalúa vs umbrales locales
        Edge-->>ESP: 201 {readingId, status, actuatorCommand:"ACTIVATE"|"NONE", recordedAt}
        ESP->>ESP: applyActuator(actuatorCommand) (deshumidificador/LED)
    end
    end

    %% ============ FASE 5: el usuario configura los umbrales ============
    rect rgb(235, 245, 255)
    note over User,BE: FASE 5 — El usuario setea/actualiza los umbrales (en el backend)
    User->>BE: POST /api/v1/authentication/sign-in
    BE-->>User: 200 {token}
    alt Primera vez (crear)
        User->>BE: POST /api/v1/environment-thresholds\n{coffeeLotId, minTemperature, maxTemperature, minHumidity, maxHumidity}
        BE-->>User: 201 {id, coffeeLotId, min/maxTemperature, min/maxHumidity}
    else Actualizar
        User->>BE: PUT /api/v1/environment-thresholds/coffee-lot/{coffeeLotId}\n{min/maxTemperature, min/maxHumidity}
        BE-->>User: 200 {id, coffeeLotId, ...}
    end
    end

    %% ============ FASE 6: sincronización en segundo plano ============
    rect rgb(240, 255, 240)
    note over Worker,BE: FASE 6 — Sync Worker (cada 30 s): sube telemetría y baja umbrales
    loop cada BACKEND_SYNC_INTERVAL_SECONDS (30 s)
        Worker->>BE: POST /api/v1/authentication/sign-in {service email/password}
        BE-->>Worker: 200 {token}

        note over Worker,BE: 6a — PUSH (outbox drain)
        Worker->>Edge: find_unsynced(batch=50) en SQLite
        loop por cada reading sin sincronizar
            Worker->>BE: POST /api/v1/telemetry-records\nAuthorization: Bearer <token>\n{coffeeLotId, temperature, humidity, timestamp}
            alt 200/201
                BE-->>Worker: 201 {id, coffeeLotId, ...}
                Worker->>Edge: mark_synced(reading.id)
            else 4xx (lote inexistente, etc.)
                BE-->>Worker: 4xx
                Worker->>Edge: mark_synced (se descarta, no reintenta)
            else 401
                BE-->>Worker: 401
                Worker->>BE: re-sign-in y reintenta una vez
            end
        end

        note over Worker,BE: 6b — PULL de umbrales (para cada device con lot_id)
        Worker->>BE: GET /api/v1/environment-thresholds/coffee-lot/{coffeeLotId}\nAuthorization: Bearer <token>
        alt 200
            BE-->>Worker: 200 {min/maxTemperature, min/maxHumidity}
            Worker->>Edge: save_current(thresholds) — actualiza umbrales locales
        else 404 (sin umbrales aún)
            BE-->>Worker: 404
            Worker->>Worker: conserva los umbrales locales actuales
        end
    end
    end

    %% ============ FASE 7: efecto de los nuevos umbrales ============
    rect rgb(255, 240, 245)
    note over ESP,Edge: FASE 7 — La siguiente lectura ya evalúa con los umbrales sincronizados
    ESP->>Edge: POST /api/v1/edge/readings (siguiente ciclo)
    Edge->>Edge: Evalúa vs umbrales recién bajados del backend
    Edge-->>ESP: 201 {actuatorCommand actualizado}
    end
```

---

## Endpoints involucrados (resumen)

### En el Edge (Flask)
| Método | Ruta | Auth | Quién la usa | Body / Respuesta |
|---|---|---|---|---|
| POST | `/api/v1/iam/devices` | — | Operador | `{device_id, lot_id}` → `201 {api_key,...}` |
| POST | `/api/v1/iam/authentication` | X-API-Key | (diagnóstico) | `{device_id}` |
| GET | `/onboarding` | — | Operador | HTML |
| GET/POST | `/api/v1/edge/account` | — | Operador | `{email, password, backendUrl}` |
| POST | `/api/v1/edge/readings` | X-API-Key | ESP32 | `{deviceId, temperature, humidity}` → `201 {status, actuatorCommand}` |
| GET | `/api/v1/edge/thresholds` | — | dashboard | umbrales actuales locales |
| PUT | `/api/v1/edge/thresholds` | X-API-Key | (override local) | `{minTemperature,...}` |
| POST | `/api/v1/edge/sync` | X-API-Key | trigger manual | fuerza push+pull |

### En el Backend (Spring, JWT Bearer)
| Método | Ruta | Quién la usa | Body / Respuesta |
|---|---|---|---|
| POST | `/api/v1/authentication/sign-in` | Usuario + Sync Worker | `{email, password}` → `{token}` |
| POST | `/api/v1/coffee-lots` | Usuario | crea el lote → `coffeeLotId` |
| POST | `/api/v1/environment-thresholds` | Usuario | `{coffeeLotId, min/maxTemperature, min/maxHumidity}` |
| PUT | `/api/v1/environment-thresholds/coffee-lot/{coffeeLotId}` | Usuario | actualiza umbrales |
| GET | `/api/v1/environment-thresholds/coffee-lot/{coffeeLotId}` | Sync Worker | baja umbrales |
| POST | `/api/v1/telemetry-records` | Sync Worker | `{coffeeLotId, temperature, humidity, timestamp}` |
| GET | `/api/v1/telemetry-records/coffee-lot/{coffeeLotId}` | Usuario/dashboard | historial |

## Notas de diseño clave
- **Dos caminos desacoplados**: el camino *device → edge* (lecturas) es siempre
  local e instantáneo contra SQLite; el camino *edge → backend* es eventual y
  lo maneja el Sync Worker. El ESP32 nunca habla con el backend.
- **`timestamp`** se manda al backend como `LocalDateTime` (UTC sin offset, sin
  `Z`) porque Jackson lo mapea a `java.time.LocalDateTime`
  (`backend_client._to_backend_timestamp`).
- **Reintentos**: en push, un 4xx marca la fila como sincronizada (no se
  reintenta); un 5xx/red corta el lote y se reintenta el siguiente ciclo. En
  cualquier request, un 401 dispara un re-sign-in y un reintento.
- **Vínculo lot_id ↔ coffeeLotId**: si el `lot_id` del device no es numérico o
  es nulo, el Edge no puede mapearlo y omite ese device en la sincronización.
