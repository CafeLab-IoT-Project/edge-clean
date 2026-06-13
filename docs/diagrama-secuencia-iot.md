# Diagrama de secuencia — CafeLab IoT (auto-enroll → umbrales → telemetría)

Cubre el ciclo de vida completo con el flujo **sin reflasheo**: el ESP32 se
auto-registra en el edge (phone-home), el operador le asigna un lote desde la web,
el usuario configura umbrales (y la cadencia de sync) en el backend, el envío de
lecturas (device → edge, local e instantáneo) y la sincronización en segundo plano
(edge ↔ backend) que sube telemetría y baja umbrales.

## Participantes

| Participante | Qué es | Repo |
|---|---|---|
| **Operador** | Provisiona el hardware, vincula la cuenta y asigna lotes | — |
| **Usuario CafeLab** | Dueño del lote; configura umbrales/cadencia desde la web | — |
| **ESP32** | Firmware TrackSilo (DHT22 + actuador); `device_id` = su MAC | `edge-clean/firmware/tracksilo-esp32` |
| **Edge** | Servicio Flask en la Raspberry Pi (SQLite local) | `edge-clean` |
| **Sync Worker** | Hilo daemon en el Edge; push event-driven + pull en cadencia configurable | `edge-clean/shared/infrastructure/sync_worker.py` |
| **Backend** | API Spring Boot CafeLab (JWT) | `cafeLab-backEnd` |

> **Vínculo de identidad**: el ESP32 se identifica con su **MAC** (`device_id`).
> El operador le **asigna** un lote desde `/onboarding`, lo que fija
> `device.lot_id` = `coffeeLotId` del backend. Ese vínculo es lo que permite al
> Edge subir telemetría al lote correcto y bajar sus umbrales
> (`_coffee_lot_id_for` en `sync_services.py`).
>
> **Sobre el `api_key`**: NO es un paso manual. El edge lo emite **automáticamente**
> en el `announce` y el ESP32 lo guarda en NVS; se reusa en cada arranque y se
> renueva solo (re-announce) si el edge lo rechaza con 401 (p. ej. tras un reset).

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
    end

    %% ============ FASE 1: vincular el edge a la cuenta del backend ============
    rect rgb(255, 250, 235)
    note over Op,BE: FASE 1 — Vincular el edge a la cuenta (onboarding)
    Op->>Edge: GET /onboarding (web)
    Op->>Edge: POST /api/v1/edge/account {email, password, backendUrl}
    Edge->>BE: POST /api/v1/authentication/sign-in
    alt Credenciales válidas
        BE-->>Edge: 200 {token}
        Edge->>Edge: Guarda cuenta + arranca Sync Worker
        Edge-->>Op: 200 {configured:true}
    else Inválidas / backend caído
        BE-->>Edge: 404 / error de red
        Edge-->>Op: 401 / 502
    end
    end

    %% ============ FASE 2: arranque del ESP32 + AUTO-ENROLL ============
    rect rgb(245, 240, 255)
    note over ESP,Edge: FASE 2 — Arranque + auto-enroll (phone-home, sin reflasheo)
    ESP->>ESP: WiFiManager (portal "TrackSilo-Setup" si no hay WiFi)
    ESP->>ESP: device_id = "esp32-" + MAC
    ESP->>Edge: Descubrir edge: mDNS _cafelab._tcp → host → IP fija
    Edge-->>ESP: IP del edge
    ESP->>Edge: POST /api/v1/iam/devices/announce {deviceId}
    Edge->>Edge: Crea Device "pendiente" (lot_id=null) + genera api_key
    Edge-->>ESP: 200 {api_key, assigned:false}
    ESP->>ESP: Guarda api_key en NVS
    end

    %% ============ FASE 3: el operador asigna un lote desde la web ============
    rect rgb(240, 255, 240)
    note over Op,BE: FASE 3 — Asignar lote al dispositivo (desde /onboarding)
    Op->>Edge: GET /api/v1/edge/devices
    Edge-->>Op: lista (el ESP32 aparece "pendiente")
    Op->>Edge: GET /api/v1/edge/lots
    Edge->>BE: GET /api/v1/coffee-lots (Bearer)
    BE-->>Edge: 200 [{id, lotName, coffeeType, ...}]
    Edge-->>Op: lotes disponibles (dropdown)
    Op->>Edge: POST /api/v1/edge/devices/{deviceId}/assign {lotId}
    Edge->>Edge: device.lot_id = coffeeLotId + despierta al Worker
    Edge-->>Op: 200 {assigned:true, lotId}
    end

    %% ============ FASE 4: envío de lecturas (local, instantáneo) ============
    rect rgb(255, 240, 245)
    note over ESP,Edge: FASE 4 — Lectura cada 30 s (device→edge, siempre local)
    loop cada READ_INTERVAL_MS (30 s)
        ESP->>ESP: Lee DHT22 (temperature, humidity)
        ESP->>Edge: POST /api/v1/edge/readings\nX-API-Key: <api_key auto>\n{deviceId, temperature, humidity}
        Edge->>Edge: Autentica (deviceId + X-API-Key)
        Edge->>Edge: Guarda reading (unsynced) + evalúa vs umbrales locales
        Edge->>Worker: notify() (despierta el push inmediato)
        Edge-->>ESP: 201 {status, actuatorCommand:"ACTIVATE"|"NONE"}
        ESP->>ESP: applyActuator(actuatorCommand)
    end
    note over ESP,Edge: Si el device aún NO tiene lote: el edge igual responde\n(usa umbrales por defecto) y bufferea sin sincronizar.
    end

    %% ============ FASE 5: el usuario configura umbrales + cadencia ============
    rect rgb(235, 245, 255)
    note over User,BE: FASE 5 — El usuario setea umbrales y la cadencia de sync (web/backend)
    User->>BE: POST /api/v1/authentication/sign-in
    BE-->>User: 200 {token}
    alt Crear
        User->>BE: POST /api/v1/environment-thresholds\n{coffeeLotId, min/maxTemperature, min/maxHumidity, syncIntervalSeconds}
        BE-->>User: 201 {...}
    else Actualizar
        User->>BE: PUT /api/v1/environment-thresholds/coffee-lot/{coffeeLotId}\n{min/max..., syncIntervalSeconds}
        BE-->>User: 200 {...}
    end
    end

    %% ============ FASE 6: sincronización en segundo plano ============
    rect rgb(240, 255, 240)
    note over Worker,BE: FASE 6 — Sync Worker: push event-driven + pull en cadencia configurable
    note over Worker,BE: 6a — PUSH (al recibir notify() o por latido)
    Worker->>Edge: find_unsynced(batch=50)
    loop por cada reading de un device CON lote
        Worker->>BE: POST /api/v1/telemetry-records (Bearer)\n{coffeeLotId, temperature, humidity, timestamp}
        BE-->>Worker: 201 → mark_synced  (4xx → descarta; 401 → re-sign-in)
    end

    note over Worker,BE: 6b — PULL de umbrales (cada syncIntervalSeconds, por reloj)
    Worker->>BE: GET /api/v1/environment-thresholds/coffee-lot/{coffeeLotId} (Bearer)
    alt 200
        BE-->>Worker: 200 {min/max..., syncIntervalSeconds}
        Worker->>Edge: save_current(thresholds) — actualiza umbrales locales
        Worker->>Worker: adopta syncIntervalSeconds como nueva cadencia
    else 404 (sin umbrales)
        BE-->>Worker: 404 → conserva los locales
    end
    end

    %% ============ FASE 7: efecto de los nuevos umbrales ============
    rect rgb(255, 240, 245)
    note over ESP,Edge: FASE 7 — La siguiente lectura ya evalúa con los umbrales sincronizados
    ESP->>Edge: POST /api/v1/edge/readings (siguiente ciclo)
    Edge-->>ESP: 201 {actuatorCommand actualizado}
    end
```

---

## Endpoints involucrados (resumen)

### En el Edge (Flask)
| Método | Ruta | Auth | Quién la usa | Body / Respuesta |
|---|---|---|---|---|
| POST | `/api/v1/iam/devices/announce` | — | ESP32 (auto-enroll) | `{deviceId}` → `200 {api_key, assigned}` |
| GET | `/onboarding` | — | Operador | HTML (cuenta + dispositivos + reset) |
| GET/POST | `/api/v1/edge/account` | — | Operador | `{email, password, backendUrl}` |
| GET | `/api/v1/edge/devices` | — | Operador/web | lista de dispositivos detectados |
| GET | `/api/v1/edge/lots` | — | Operador/web | lotes del backend (para asignar) |
| POST | `/api/v1/edge/devices/{id}/assign` | — | Operador/web | `{lotId}` → fija `device.lot_id` |
| POST | `/api/v1/edge/devices/reset` | — | Operador/web | borra IoT + lecturas (mantiene cuenta) |
| POST | `/api/v1/edge/readings` | X-API-Key (auto) | ESP32 | `{deviceId, temperature, humidity}` → `201 {status, actuatorCommand}` |
| GET | `/api/v1/edge/thresholds` | — | dashboard | umbrales actuales locales |
| GET | `/api/v1/edge/sync/status` | — | diagnóstico | pendientes, cadencia, worker |
| POST | `/api/v1/edge/sync` | X-API-Key | trigger manual | fuerza push+pull |

> Legacy: `POST /api/v1/iam/devices` (registro manual con `lot_id`) sigue
> existiendo pero **ya no es el flujo**; lo reemplazó `announce` + asignación web.

### En el Backend (Spring, JWT Bearer)
| Método | Ruta | Quién la usa | Body / Respuesta |
|---|---|---|---|
| POST | `/api/v1/authentication/sign-in` | Usuario + Edge/Worker | `{email, password}` → `{token}` |
| POST | `/api/v1/coffee-lots` | Usuario | crea el lote → `coffeeLotId` |
| GET | `/api/v1/coffee-lots` | Edge (asignación) | lotes del usuario |
| POST/PUT | `/api/v1/environment-thresholds[/coffee-lot/{id}]` | Usuario | `{min/max..., syncIntervalSeconds}` |
| GET | `/api/v1/environment-thresholds/coffee-lot/{id}` | Sync Worker | baja umbrales + cadencia |
| POST | `/api/v1/telemetry-records` | Sync Worker | `{coffeeLotId, temperature, humidity, timestamp}` |
| GET | `/api/v1/telemetry-records/coffee-lot/{id}` | Usuario/dashboard | historial |

## Notas de diseño clave
- **Sin reflasheo**: firmware genérico; `device_id` = MAC; `api_key` emitida en el
  `announce` y guardada en NVS. El lote se asigna desde la web, no en el firmware.
- **Descubrimiento del edge**: por servicio mDNS `_cafelab._tcp` (preferido),
  luego hostname, luego IP fija (`resolveEdge()` en el `.ino`).
- **Dos caminos desacoplados**: *device → edge* (lecturas) siempre local e
  instantáneo; *edge → backend* eventual vía Sync Worker. El ESP32 nunca habla
  con el backend.
- **Push event-driven**: cada lectura despierta al Worker (`notify()`), así la
  telemetría sube casi al instante en vez de esperar el poll.
- **Cadencia configurable**: el backend puede mandar `syncIntervalSeconds` en el
  payload de umbrales; el Worker adopta esa cadencia en caliente.
- **`timestamp`** se manda como `LocalDateTime` (UTC sin `Z`) por Jackson
  (`backend_client._to_backend_timestamp`).
- **Vínculo lot_id ↔ coffeeLotId**: si el device no tiene lote asignado, el Edge
  bufferea sus lecturas pero no las sincroniza hasta que se le asigne uno.
