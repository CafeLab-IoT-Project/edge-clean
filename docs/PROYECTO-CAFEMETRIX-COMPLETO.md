# CafeMetrix / CafeLab — Documento maestro del proyecto

> **Propósito de este documento:** servir de fuente única y completa para
> construir una presentación (PPT). Cubre **qué es el sistema, su arquitectura,
> cada componente, las funciones, los endpoints, los flujos y las conexiones
> entre el IoT, el edge, el backend y el frontend.** Está pensado para que un
> agente pueda extraer secciones y armar diapositivas sin tener que leer el
> código.

---

## 1. Resumen ejecutivo (elevator pitch)

**CafeMetrix (producto: CafeLab)** es una plataforma IoT para el **monitoreo
ambiental de lotes de café almacenado**. Sensores físicos (ESP32 + DHT22) miden
**temperatura y humedad** dentro de los silos/almacenes de café; un **edge**
local (Raspberry Pi) evalúa esas lecturas **al instante** contra umbrales de
seguridad y acciona dos **actuadores independientes** (humedad y temperatura)
cuando alguna variable se sale de rango; en segundo plano,
el edge **sincroniza** la telemetría con un **backend en la nube** donde el
usuario visualiza histórico, analítica, alertas y configura los umbrales.

**Problema que resuelve:** el café almacenado pierde calidad (moho, fermentación,
pérdida de aroma) si la temperatura/humedad se salen de rango. CafeLab da
**vigilancia continua + reacción automática + trazabilidad** por lote.

**Lo distintivo (arquitectura edge-first):**
- El control crítico (encender el actuador) ocurre **en local**, en milisegundos,
  **sin depender de internet**.
- La nube es para **histórico, analítica y configuración**, no para el control en
  tiempo real → resiliencia ante caídas de red.
- **Provisioning sin reflasheo**: un mismo firmware genérico sirve para todos los
  dispositivos; el sensor se **auto-registra** (phone-home) y se le asigna un lote
  desde una web, sin tocar código por dispositivo.

---

## 2. Arquitectura de alto nivel

```
┌──────────────┐   WiFi LAN     ┌─────────────────────┐   Internet/HTTPS   ┌────────────────────┐
│  ESP32 +     │  HTTP local    │  EDGE (Raspberry Pi)│   JWT (Bearer)     │  BACKEND (Azure)   │
│  DHT22       │ ─────────────► │  Flask + SQLite     │ ─────────────────► │  Spring Boot+MySQL │
│ "TrackSilo"  │ ◄───────────── │  (decisión local)   │ ◄───────────────── │                    │
│ +2 actuadores│  hum/temp alert│  + Sync Worker      │   umbrales/cadencia│                    │
└──────────────┘                └─────────────────────┘                    └─────────┬──────────┘
                                                                                     │ REST/JWT
                                                                           ┌─────────▼──────────┐
                                                                           │ FRONTEND (Firebase)│
                                                                           │  Angular 20 (SPA)  │
                                                                           │  dashboard/alertas │
                                                                           └────────────────────┘
```

**Tres capas, tres repos:**

| Capa | Repo | Tecnología | Despliegue |
|---|---|---|---|
| **Dispositivo (IoT)** | `edge-clean/firmware/tracksilo-esp32` | C++ (Arduino), ESP32, DHT22 | Flasheo USB |
| **Edge** | `edge-clean` | Python, Flask, Peewee, SQLite | Raspberry Pi (systemd) |
| **Backend** | `cafeLab-backEnd` | Java 24, Spring Boot 3.5, MySQL, JWT | Azure |
| **Frontend** | `cafeLab-frontend` | Angular 20, RxJS, ngx-translate | Firebase Hosting |

**Principio rector — dos caminos desacoplados:**
1. **device → edge** (lecturas + comando de actuador): **siempre local, instantáneo**, funciona sin internet.
2. **edge → backend** (telemetría histórica + umbrales): **eventual**, en segundo plano vía *Sync Worker*. **El ESP32 nunca habla con el backend.**

---

## 3. El dispositivo IoT — "TrackSilo" (ESP32 + DHT22)

**Hardware:**
- **ESP32** (microcontrolador con WiFi).
- **DHT22**: sensor de temperatura y humedad (pin de datos GPIO 4).
- **Dos actuadores independientes**: actuador de **humedad** (GPIO 18, p. ej.
  deshumidificador) y actuador de **temperatura** (GPIO 19, p. ej.
  enfriador/calefactor).

**Firmware genérico** (`tracksilo-esp32.ino`) — el mismo binario para todos los dispositivos:

| Característica | Detalle |
|---|---|
| **Identidad** | `device_id = "esp32-" + MAC` (auto). Editable con `DEVICE_ID_OVERRIDE` para simular otro IoT. |
| **WiFi** | **WiFiManager**: si no hay red guardada, abre el portal cautivo `TrackSilo-Setup` para configurar el WiFi desde el celular. |
| **Descubrimiento del edge** | Cascada `resolveEdge()`: 1) servicio **mDNS `_cafelab._tcp`** (lo más fiable en ESP32), 2) hostname mDNS (`raspberrypi`), 3) **IP fija de respaldo**. |
| **Auto-enrollment (phone-home)** | `POST /api/v1/iam/devices/announce {deviceId}` → el edge devuelve la `api_key`, que se guarda en **NVS** (memoria no volátil, librería Preferences). |
| **Loop** | Cada **30 s** lee el DHT22 y hace `POST /api/v1/edge/readings` con la `X-API-Key`. |
| **Reacción** | Lee `humidityAlert` y `temperatureAlert` de la respuesta y enciende de forma independiente el **pin 18** (humedad) y el **pin 19** (temperatura). |
| **Auto-recuperación** | Si recibe `401` (p. ej. el edge fue reseteado), borra la key y **se re-anuncia** automáticamente. |

**Librerías:** WiFiManager (tzapu), DHT sensor library (Adafruit) + Adafruit Unified Sensor, ArduinoJson v7. (ESPmDNS / WiFi / HTTPClient / Preferences vienen con el core ESP32.)

**Por qué "sin reflasheo" importa:** antes había que hornear `device_id`, `api_key`
y lote en cada placa. Ahora el firmware es idéntico para todos; toda la
identidad y la asignación de lote se resuelven **en runtime**.

### 3.1. Simulador (para demos sin hardware)
`simulator/tracksilo_sim.py` — réplica en Python del firmware. Se anuncia igual,
manda lecturas y aplica el actuador "en pantalla". Útil para presentar el flujo
sin un ESP32 físico.

```bash
# se anuncia y manda lecturas cada 5s
python tracksilo_sim.py --edge http://raspberrypi.local:5000
# simula otro dispositivo distinto
python tracksilo_sim.py --device-id esp32-sim-02
# escenario "humedad alta" (dispara el actuador), 3 lecturas
python tracksilo_sim.py --profile humid --count 3
```
Perfiles: `optimal`, `hot`, `humid`, `random`.

---

## 4. El Edge (Raspberry Pi) — corazón del sistema

**Stack:** Python · Flask · Peewee (ORM) · SQLite (`edge_clean.db`, modo WAL) · requests · python-dateutil.

**Responsabilidades:**
1. Recibir lecturas del ESP32 y responder **al instante** con estado + comando de actuador.
2. Almacenar todo localmente (resiliencia offline).
3. Gestionar la identidad de los dispositivos (auto-enroll, api_keys).
4. Sincronizar en segundo plano con el backend (subir telemetría, bajar umbrales).
5. Servir la web de onboarding (vincular cuenta + asignar lotes + reset).

### 4.1. Arquitectura interna (DDD por capas)
Tres *bounded contexts*, cada uno en capas `domain / application / infrastructure / interfaces`:

| Contexto | Qué hace |
|---|---|
| **`iam`** | Identidad de dispositivos: registro, auto-enroll (announce), autenticación por `api_key`, asignación de lote, reset. |
| **`iotmonitoring`** | Lógica de negocio: lecturas, umbrales, evaluación de estado, eventos de actuador, sincronización con backend, onboarding web. |
| **`shared`** | Infraestructura común: base de datos, configuración, Sync Worker. |

### 4.2. Lógica de dominio (las reglas de negocio)
**Evaluación de estado** (`StorageConditionService.evaluate`):

| Condición | `status` |
|---|---|
| `temperatura > maxTemp` **o** `humedad > maxHum` | **`DANGER`** |
| `temperatura < minTemp` **o** `humedad < minHum` | **`WARNING`** |
| Todo dentro de rango | **`OPTIMAL`** |

**Alertas por variable** (`environmental_alerts`) — dos banderas independientes que
controlan un actuador cada una:
- `humidityAlert` = `true` si la humedad está **fuera de rango** (`> maxHum` **o** `< minHum`) → firmware enciende **pin 18**.
- `temperatureAlert` = `true` si la temperatura está **fuera de rango** (`> maxTemp` **o** `< minTemp`) → firmware enciende **pin 19**.

**Comando de actuador** (`actuator_command`, *legacy/compatibilidad*):
- Sigue existiendo en la respuesta como `actuatorCommand` (`ACTIVATE` si `humedad > maxHum`, si no `NONE`).
- Es el control histórico de un solo actuador (humedad). Las nuevas banderas `humidityAlert`/`temperatureAlert` lo superan y son lo que usa el firmware.
- Los **eventos del actuador** (`actuator_events`) se siguen registrando solo para la activación por humedad alta; el control de los dos pines es **en vivo**, sin historial separado por tipo.

**Umbrales por defecto** (si un dispositivo aún no tiene umbrales): 18–22 °C / 55–65 % HR.

**Rangos permitidos para umbrales:** Temp 10–30 °C, Humedad 40–80 %.
**Rango físico del sensor (validación de lectura):** Temp −40 a 80 °C, Humedad 0–100 %.

**Estado de conexión del sensor:** si la última lectura tiene > **120 s**, el sensor se considera **`OFFLINE`**, si no **`ONLINE`**.

### 4.3. Modelo de datos (SQLite)

| Tabla | Campos clave | Rol |
|---|---|---|
| `devices` | `device_id` (PK = MAC), `api_key`, `lot_id` (→ coffeeLotId), `created_at` | Identidad del IoT |
| `sensor_readings` | `device_id`, `temperature`, `humidity`, `recorded_at`, **`is_synced`**, `synced_at` | Lecturas + **patrón outbox** |
| `storage_thresholds` | `device_id`, `min/max temperature`, `min/max humidity`, `is_current` | Umbrales locales (espejo del backend) |
| `actuator_events` | `device_id`, `event_type`, `triggered_at`, `resolved_at` | Historial de activaciones (solo local) |
| `backend_account` | `base_url`, `email`, `password`, `updated_at` | Cuenta CafeLab vinculada (fila única) |

**Vínculo de identidad clave:** `device.lot_id` (edge) = `coffeeLotId` (backend). Sin lote asignado, el edge **bufferea** las lecturas pero **no las sincroniza**.

### 4.4. Sync Worker (sincronización edge ↔ backend)
Hilo daemon (`sync_worker.py`) que desacopla el camino local del camino a la nube.

- **PUSH event-driven:** cada lectura nueva llama a `worker.notify()` → el worker se despierta y **empuja al instante** (latencia ≈ un round-trip de red, no espera al poll). Patrón **outbox**: lee `find_unsynced(batch=50)`, postea a `/telemetry-records`, marca `is_synced`. Errores 4xx → descarta la fila (no reintenta), 5xx/red → reintenta el próximo ciclo, 401 → re-firma JWT.
- **PULL en cadencia (por reloj):** cada `syncIntervalSeconds` baja los umbrales del backend (`GET /environment-thresholds/coffee-lot/{id}`) y los aplica localmente. La cadencia es **configurable desde el backend/UI** y el worker la **adopta en caliente** (default 10 s, mínimo 5 s).

### 4.5. Configuración (variables de entorno)

| Variable | Default | Descripción |
|---|---|---|
| `BACKEND_BASE_URL` | `http://localhost:8080` | URL del backend |
| `BACKEND_SERVICE_EMAIL` / `_PASSWORD` | — | Credenciales de la cuenta de servicio |
| `BACKEND_SYNC_ENABLED` | `true` | Activa la sincronización |
| `BACKEND_SYNC_INTERVAL_SECONDS` | `10` | Periodo del worker |
| `BACKEND_TIMEOUT_SECONDS` | `10` | Timeout HTTP |
| `EDGE_LOG_LEVEL` | `INFO` | Nivel de log al journal |

Sin credenciales → la sync queda **deshabilitada** y el edge corre **100 % standalone**. Las credenciales vinculadas por la web **tienen prioridad** sobre las env vars (`BackendConfig.resolve()`).

---

## 5. Endpoints del Edge (Flask)

**Base:** `http://<edge>:5000` (p. ej. `http://raspberrypi.local:5000`).

### 5.1. Health & IAM
| Método | Ruta | Auth | Quién | Descripción |
|---|---|---|---|---|
| GET | `/` | — | cualquiera | Health check `{"status":"ok"}` |
| POST | `/api/v1/iam/devices/announce` | — | **ESP32** | Auto-enroll: `{deviceId}` → `200 {api_key, assigned}` |
| POST | `/api/v1/iam/devices` | — | (legacy) | Registro manual con `lot_id` → `201 {device, api_key}` |
| POST | `/api/v1/iam/authentication` | `X-API-Key` | diagnóstico | Valida `deviceId` + api_key |
| GET | `/api/v1/iam/devices` | — | diagnóstico | Lista todos los dispositivos |

### 5.2. Monitoreo IoT / Edge
| Método | Ruta | Auth | Quién | Descripción |
|---|---|---|---|---|
| POST | `/api/v1/edge/readings` | `X-API-Key` | **ESP32** | Registra lectura → `201 {status, actuatorCommand, humidityAlert, temperatureAlert}` |
| GET | `/api/v1/edge/readings/latest` | — | dashboard | Última lectura con estado |
| GET | `/api/v1/edge/readings?limit=N` | — | dashboard | Lecturas recientes (1–100) |
| GET | `/api/v1/edge/thresholds` | — | dashboard | Umbrales locales actuales |
| PUT | `/api/v1/edge/thresholds` | `X-API-Key` | admin | Actualiza umbrales |
| GET | `/api/v1/edge/sensor-status` | — | dashboard | `ONLINE`/`OFFLINE` |
| GET | `/api/v1/edge/actuator-events?limit=N` | — | dashboard | Eventos del actuador |
| POST | `/api/v1/edge/sync` | `X-API-Key` | trigger manual | Fuerza push+pull → contadores |
| GET | `/api/v1/edge/sync/status` | — | diagnóstico | `{pendingReadings, syncEnabled, workerRunning, intervalSeconds}` |

### 5.3. Onboarding (web + cuenta + lotes)
| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/onboarding` | — | Página HTML: vincular cuenta + dispositivos + asignar + reset |
| GET / POST | `/api/v1/edge/account` | — | Estado / vincular cuenta `{email, password, backendUrl}` (valida contra el backend) |
| GET | `/api/v1/edge/devices` | — | Dispositivos detectados (con lote, lecturas, último visto) |
| GET | `/api/v1/edge/lots` | — | Lotes del backend para el dropdown (409 si no hay cuenta) |
| POST | `/api/v1/edge/devices/{id}/assign` | — | Asigna lote: fija `device.lot_id` y despierta el worker |
| POST | `/api/v1/edge/devices/reset` | — | Borra dispositivos IoT + telemetría (**mantiene la cuenta**) |

**Ejemplo de respuesta de lectura (temperatura y humedad altas):**
```json
{ "readingId": 1, "deviceId": "esp32-aabbcc", "temperature": 25.5,
  "humidity": 70.2, "status": "DANGER", "actuatorCommand": "ACTIVATE",
  "humidityAlert": true, "temperatureAlert": true,
  "recordedAt": "2026-05-31T07:00:00Z" }
```

---

## 6. El Backend (Spring Boot, Azure)

**Stack:** Java 24 · Spring Boot 3.5 · MySQL (Hibernate `ddl-auto=update`) · **JWT** (jjwt) · Lombok · Swagger/OpenAPI. **Arquitectura DDD** (`domain/application/infrastructure/interfaces`) con CQRS (commands/queries) por *bounded context*.

**Bounded context relevante al IoT — `monitoring`:**
- **`TelemetryRecord`** (aggregate): `coffeeLotId`, `temperature`, `humidity`, `timestamp` (`LocalDateTime`). Histórico de telemetría.
- **`EnvironmentThreshold`** (aggregate): `coffeeLotId` (único), `TemperatureThreshold` (min/max), `HumidityThreshold` (min/max), **`syncIntervalSeconds`**. Fuente de verdad de los umbrales.

**Otros contextos** (catálogo completo de la plataforma CafeLab, más allá del IoT): `iam`, `production` (coffee-lots, roast-profiles, suppliers), `coffees`, `calibrations`, `cuppingsessions`, `defects`, `preparation` (recipes, portfolios, ingredients), `management` (inventario, costos de producción), `profiles`. → El IoT es **un módulo** dentro de una suite mayor de gestión de café de especialidad.

### 6.1. Endpoints del backend relevantes (JWT Bearer)
| Método | Ruta | Quién | Body / Respuesta |
|---|---|---|---|
| POST | `/api/v1/authentication/sign-in` | Usuario + Edge | `{email, password}` → `{id, email, token}` |
| POST | `/api/v1/authentication/sign-up` | Usuario | crea cuenta |
| POST / GET | `/api/v1/coffee-lots` | Usuario / Edge | crea lote (`coffeeLotId`) / lista lotes |
| POST | `/api/v1/telemetry-records` | **Sync Worker** | `{coffeeLotId, temperature, humidity, timestamp}` → `201` |
| GET | `/api/v1/telemetry-records/coffee-lot/{id}` | Frontend | histórico del lote |
| POST | `/api/v1/environment-thresholds` | Usuario | crea umbrales `{coffeeLotId, min/max..., syncIntervalSeconds}` |
| PUT | `/api/v1/environment-thresholds/coffee-lot/{id}` | Usuario | actualiza umbrales + cadencia |
| GET | `/api/v1/environment-thresholds/coffee-lot/{id}` | **Sync Worker** + Frontend | baja umbrales + cadencia |

**Detalle de integración:** el `timestamp` se manda como `LocalDateTime` UTC **sin `Z`** (Jackson no acepta offset). Lo normaliza `backend_client._to_backend_timestamp`.

---

## 7. El Frontend (Angular, Firebase)

**Stack:** Angular 20 (standalone components) · RxJS (polling `interval`+`startWith`+`switchMap`) · ngx-translate (i18n) · Angular Material.

**Módulo `monitoring`** (DDD en frontend: `domain / application / infrastructure / presentation`):

| Vista | Qué muestra | Polling |
|---|---|---|
| **Lots page** | Tarjetas por lote: T/H actual, estado, cobertura de telemetría | **5 s** |
| **Alerts page** | Alertas (critical/warning) derivadas de la telemetría, filtros, marcar leídas | **5 s** |
| **Analytics page** | KPIs (T/H promedio 24h), tendencias, health score, eventos recientes | **5 s** |
| **Configuration page** | Edita umbrales **y la cadencia de sync** (`syncIntervalSeconds`, +/− 5, mín 5) | — |
| **Monitoring hub** | Landing del módulo | — |

**Cómo llega el dato a pantalla:** las vistas hacen **polling cada 5 s** a los endpoints del backend (`telemetry-records`, `environment-thresholds`, etc.). El dato no se "empuja"; el frontend lo **consulta** periódicamente. Latencia total de extremo a extremo ≈ (lectura → edge instantáneo) + (push event-driven a backend) + (≤ 5 s de polling del frontend).

**El frontend es también la consola de configuración:** ahí el usuario fija los umbrales y la cadencia de sync que el edge luego **baja** y aplica.

---

## 8. Flujo end-to-end (el recorrido completo del dato)

**Fases del ciclo de vida** (ver diagrama de secuencia detallado en
[`diagrama-secuencia-iot.md`](diagrama-secuencia-iot.md)):

0. **Prerequisito:** el usuario crea su cuenta y un **lote de café** en el backend.
1. **Vincular el edge:** el operador entra a `/onboarding` del edge y vincula la cuenta CafeLab (el edge valida con un sign-in).
2. **Arranque + auto-enroll:** el ESP32 configura WiFi (WiFiManager), descubre el edge (mDNS), se **anuncia** (`announce`) y recibe su `api_key` (la guarda en NVS). Aparece como **"pendiente"**.
3. **Asignar lote:** desde `/onboarding` el operador elige un lote (dropdown poblado desde el backend) y lo **asigna** al dispositivo → `device.lot_id = coffeeLotId`.
4. **Lecturas (local, instantáneo):** cada 30 s el ESP32 manda `temperature/humidity` → el edge **evalúa**, guarda, responde `status + humidityAlert + temperatureAlert` y **despierta al worker**. El ESP32 enciende cada actuador (pin 18 humedad / pin 19 temperatura) según su bandera.
5. **Configuración (nube):** el usuario fija umbrales y `syncIntervalSeconds` desde el frontend/backend.
6. **Sync en segundo plano:** el worker **sube** la telemetría (push event-driven) y **baja** los umbrales + cadencia (pull por reloj).
7. **Efecto:** la siguiente lectura ya se evalúa con los umbrales sincronizados.
8. **Visualización:** el frontend hace polling (5 s) y muestra histórico, KPIs y alertas.

**Resiliencia:** si se cae internet, los pasos 4 (control local) siguen funcionando; las lecturas se bufferean (outbox) y se sincronizan cuando vuelve la red.

---

## 9. Decisiones de diseño destacadas (para la diapositiva de "por qué así")

| Decisión | Razón |
|---|---|
| **Edge-first (control local)** | El actuador no puede esperar a la nube; debe reaccionar aunque no haya internet. |
| **Outbox + Sync Worker** | Desacopla la latencia del dispositivo de la disponibilidad de la red. Cero pérdida de datos offline. |
| **Push event-driven (`notify()`)** | La telemetría sube casi al instante en lugar de esperar el poll. |
| **Cadencia configurable en caliente** | El usuario ajusta cada cuánto re-baja umbrales sin reiniciar el edge. |
| **Auto-enroll sin reflasheo** | Un firmware genérico para todos; identidad por MAC + api_key en runtime. Escala a N dispositivos sin tocar código. |
| **Descubrimiento por servicio mDNS** | `queryHost` es poco fiable en ESP32; `_cafelab._tcp` + IP fija de respaldo lo hacen robusto. |
| **DDD por capas en los 3 repos** | Consistencia arquitectónica, dominio aislado de la infraestructura. |
| **api_key emitida automáticamente** | El usuario ya autorizó la red local; la key se gestiona sola (no se hornea ni se hardcodea). |

---

## 10. Despliegue / operación (resumen)

| Componente | Dónde | Cómo |
|---|---|---|
| **Edge** | Raspberry Pi | `systemd` (`cafelab-edge.service`), arranca al boot. Logs: `journalctl -u cafelab-edge -f`. Portal WiFi: `cafelab-wifi-portal.service`. mDNS: Avahi. |
| **Backend** | Azure | Spring Boot (jar) + MySQL. |
| **Frontend** | Firebase Hosting | `ng build` + `firebase deploy`. |
| **Firmware** | ESP32 | Flasheo USB desde Arduino IDE. |

**Docs operativas en el repo edge:** `deploy/GUIA-DESPLIEGUE.md` (runbook), `deploy/raspberrypi/CONFIGURACION-PI.md` (chuleta systemd/journalctl), `deploy/raspberrypi/edge-discovery.md` (mDNS), `deploy/PRUEBA-E2E-ESP32.md` (prueba end-to-end), `firmware/tracksilo-esp32/README.md`.

---

## 11. Glosario rápido

- **TrackSilo** — nombre del dispositivo sensor (ESP32 + DHT22).
- **Edge** — servicio Flask en la Raspberry Pi que decide localmente.
- **Sync Worker** — hilo del edge que sincroniza con el backend.
- **Phone-home / announce** — el dispositivo se auto-registra y recibe su `api_key`.
- **Outbox** — patrón: cada lectura se guarda con `is_synced=false` hasta confirmarse en la nube.
- **coffeeLotId / lot_id** — vínculo de identidad lote↔dispositivo.
- **Umbral (threshold)** — rango seguro de T/H, configurado en el backend, aplicado en el edge.
- **Actuadores** — dos salidas independientes que el edge controla vía `humidityAlert` (pin 18) y `temperatureAlert` (pin 19) cuando cada variable se sale de rango.

---

## 12. Datos rápidos para diapositivas (cifras y constantes)

- Intervalo de lectura del ESP32: **30 s**.
- Polling del frontend: **5 s**.
- Cadencia de sync edge↔backend: **10 s** (configurable, mín **5 s**).
- Sensor `OFFLINE` tras: **120 s** sin lecturas.
- Actuadores: **2 independientes** — humedad (pin 18) y temperatura (pin 19), cada uno se activa si su variable sale de rango (`> max` o `< min`).
- Umbrales por defecto: **18–22 °C / 55–65 % HR**.
- Rango permitido de umbrales: **10–30 °C / 40–80 % HR**.
- Batch de push del outbox: **50** lecturas.
- JWT del backend: **Bearer**, renovado automáticamente ante `401`.
- 3 repos · 3 capas · 1 firmware genérico para N dispositivos.
