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
