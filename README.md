# edge-clean

Edge API para el dispositivo IoT TrackSilo de CafeLab. El servicio recibe
lecturas ambientales, evalua umbrales de temperatura/humedad y responde con el
estado ambiental y el comando del actuador.

## Stack

- Python
- Flask
- Peewee
- SQLite
- python-dateutil

## Ejecutar

```powershell
pip install -r requirements.txt
python app.py
```

Base local por defecto:

```text
edge_clean.db
```

Al primer request se inicializan las tablas y se crea un dispositivo de
desarrollo:

```text
deviceId: tracksilo-001
X-API-Key: test-api-key-123
```

Base URL local:

```text
http://127.0.0.1:5000
```

## Endpoints

### Health check

| Metodo | Endpoint | Auth | Descripcion |
|---|---|---|---|
| GET | `/` | No | Verifica que la API esta activa |

### IAM

| Metodo | Endpoint | Auth | Descripcion |
|---|---|---|---|
| POST | `/api/v1/iam/devices` | No | Registra un dispositivo y genera API key |
| POST | `/api/v1/iam/authentication` | `X-API-Key` | Valida `deviceId` + API key |

### IoT Monitoring / Edge

| Metodo | Endpoint | Auth | Descripcion |
|---|---|---|---|
| GET | `/api/v1/edge/thresholds` | No | Obtiene los umbrales actuales |
| PUT | `/api/v1/edge/thresholds` | `X-API-Key` | Actualiza umbrales |
| POST | `/api/v1/edge/readings` | `X-API-Key` | Registra una lectura y devuelve estado/comando |
| GET | `/api/v1/edge/readings/latest` | No | Obtiene la lectura mas reciente |
| GET | `/api/v1/edge/readings` | No | Lista lecturas recientes |
| GET | `/api/v1/edge/sensor-status` | No | Consulta estado ONLINE/OFFLINE del sensor |
| GET | `/api/v1/edge/actuator-events` | No | Lista eventos recientes del actuador |
| POST | `/api/v1/edge/sync` | `X-API-Key` | Fuerza una sincronizacion con el backend |

Los endpoints protegidos requieren:

```text
Content-Type: application/json
X-API-Key: test-api-key-123
```

Tambien deben enviar `deviceId` en el body JSON.

## Requests de prueba

### Health check

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/"
```

### Registrar dispositivo

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/iam/devices" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{
    "deviceId": "tracksilo-002",
    "lotId": "lot-001"
  }'
```

### Autenticar dispositivo

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/iam/authentication" `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ "X-API-Key" = "test-api-key-123" } `
  -Body '{
    "deviceId": "tracksilo-001"
  }'
```

### Consultar umbrales

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/edge/thresholds?deviceId=tracksilo-001"
```

### Actualizar umbrales

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/edge/thresholds" `
  -Method Put `
  -ContentType "application/json" `
  -Headers @{ "X-API-Key" = "test-api-key-123" } `
  -Body '{
    "deviceId": "tracksilo-001",
    "minTemperature": 10,
    "maxTemperature": 24,
    "minHumidity": 40,
    "maxHumidity": 68
  }'
```

### Registrar lectura

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/edge/readings" `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ "X-API-Key" = "test-api-key-123" } `
  -Body '{
    "deviceId": "tracksilo-001",
    "temperature": 25.5,
    "humidity": 70.2
  }'
```

Respuesta esperada con humedad elevada:

```json
{
  "readingId": 1,
  "deviceId": "tracksilo-001",
  "temperature": 25.5,
  "humidity": 70.2,
  "status": "DANGER",
  "actuatorCommand": "ACTIVATE",
  "humidityAlert": true,
  "temperatureAlert": true,
  "recordedAt": "2026-05-31T07:00:00Z"
}
```

### Consultar ultima lectura

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/edge/readings/latest?deviceId=tracksilo-001"
```

### Consultar lecturas recientes

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/edge/readings?deviceId=tracksilo-001&limit=10"
```

### Consultar estado del sensor

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/edge/sensor-status?deviceId=tracksilo-001"
```

### Consultar eventos del actuador

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/v1/edge/actuator-events?deviceId=tracksilo-001&limit=10"
```

## Reglas actuales

- Si la humedad supera `maxHumidity`, el estado es `DANGER` y el comando es
  `ACTIVATE`.
- Si la temperatura supera `maxTemperature`, el estado es `DANGER`, pero el
  comando sigue siendo `NONE`.
- Si temperatura o humedad estan por debajo de sus minimos, el estado es
  `WARNING`.
- Si todo esta dentro del rango, el estado es `OPTIMAL`.
- Si el sensor no envia lecturas por mas de 2 minutos, se considera `OFFLINE`.

### Alertas por variable (actuadores independientes)

Ademas del `actuatorCommand` (que solo controla el actuador de humedad, por
compatibilidad), la respuesta de `POST /api/v1/edge/readings` incluye dos
banderas independientes que el firmware usa para encender un actuador por
variable:

- `humidityAlert`: `true` cuando la humedad esta **fuera de rango**
  (`> maxHumidity` o `< minHumidity`). El firmware enciende el **pin 18**.
- `temperatureAlert`: `true` cuando la temperatura esta **fuera de rango**
  (`> maxTemperature` o `< minTemperature`). El firmware enciende el **pin 19**.

Estas banderas tambien aparecen en `GET /readings/latest` y `GET /readings`. El
control es en vivo (no se persiste un historial separado por tipo de actuador).

## Sincronizacion con el backend (edge -> backend)

El edge funciona de forma autonoma frente al dispositivo (responde el comando del
actuador al instante, incluso sin internet) y reconcilia los datos con el backend
Java de CafeLab en segundo plano.

Flujo:

1. **Identidad**: el edge actua como cuenta de servicio. Firma con
   `POST /api/v1/authentication/sign-in` (email + password), cachea el JWT y lo
   renueva automaticamente ante un `401`.
2. **Mapeo**: cada dispositivo se asocia a un `coffeeLotId` numerico del backend a
   traves de su campo `lotId`. Sin `lotId`, ese dispositivo no se sincroniza.
3. **Outbox**: cada lectura se guarda localmente con `is_synced = false`. Un worker
   en segundo plano envia las pendientes a `POST /api/v1/telemetry-records` y las
   marca como sincronizadas. Si el backend no responde, se reintenta en el
   siguiente ciclo (resiliencia offline).
4. **Umbrales**: el backend es la fuente de verdad. El worker hace pull de
   `GET /api/v1/environment-thresholds/coffee-lot/{coffeeLotId}` y actualiza los
   umbrales locales. Los eventos del actuador permanecen solo en el edge.

### Configuracion (variables de entorno)

| Variable | Default | Descripcion |
|---|---|---|
| `BACKEND_BASE_URL` | `http://localhost:8080` | URL del backend Java |
| `BACKEND_SERVICE_EMAIL` | — | Email de la cuenta de servicio |
| `BACKEND_SERVICE_PASSWORD` | — | Password de la cuenta de servicio |
| `BACKEND_SYNC_ENABLED` | `true` | Activa la sincronizacion |
| `BACKEND_SYNC_INTERVAL_SECONDS` | `30` | Periodo del worker |
| `BACKEND_TIMEOUT_SECONDS` | `5` | Timeout de las llamadas HTTP |

Si no se definen `BACKEND_SERVICE_EMAIL` y `BACKEND_SERVICE_PASSWORD`, la
sincronizacion queda **deshabilitada** y el edge corre de forma 100% standalone
(comportamiento original).

### Vinculacion de cuenta (onboarding)

En lugar de configurar las env vars `BACKEND_SERVICE_*` a mano, el usuario puede
vincular el edge a su cuenta CafeLab desde una pantalla del propio edge:

- `GET /onboarding` — formulario web de login.
- `POST /api/v1/edge/account` — body `{email, password, backendUrl?}`. El edge
  valida las credenciales con un sign-in contra el backend; si son correctas las
  guarda y arranca la sincronizacion.
- `GET /api/v1/edge/account` — indica si ya hay cuenta vinculada (no expone la
  contraseña).

Las credenciales guardadas **tienen prioridad** sobre las env vars
(`BackendConfig.resolve()`). Nota: por el diseño del backend (JWT de 7 dias sin
refresh) el edge guarda la contraseña localmente; en produccion deberia cifrarse.
