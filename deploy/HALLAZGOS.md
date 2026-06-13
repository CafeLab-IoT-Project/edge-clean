# Hallazgos del despliegue y prueba E2E (edge ↔ backend)

Registro de lo encontrado al desplegar el edge en una Raspberry Pi y validar el
flujo completo contra el backend Java. Fecha: 2026-06-06.

## Estado: flujo E2E CONFIRMADO ✅

Probado de punta a punta (backend en Docker local + edge real en el Pi):

| Paso | Resultado |
|---|---|
| Cuenta creada (`POST /api/v1/profiles`) | `dueno@cafelab.com` (perfil + usuario IAM vinculados) |
| Edge vinculado a la cuenta (`POST /api/v1/edge/account`) | `configured:true` |
| Dispositivo registrado | `tracksilo-e2e` → `lot_id=1` (= coffeeLotId) |
| ESP32 simulado → edge | `20/60` → OPTIMAL/NONE; `24/72` → DANGER/ACTIVATE |
| Sync edge→backend (`POST /api/v1/edge/sync`) | `readingsPushed:2, thresholdsUpdated:1` |
| Telemetría en el backend | `telemetry-records/coffee-lot/1` → 2 registros |
| Umbrales sincronizados al edge | edge bajó 15-25 / 50-70 desde el backend |

## Hallazgos / gotchas (causa → solución)

### 1. wifi-connect: la UI es un asset SEPARADO (causaba 404 en el portal)
El tarball del binario (`wifi-connect-<arch>.tar.gz`) **solo trae el ejecutable**.
La web del portal viene aparte en **`wifi-connect-ui.tar.gz`**. Sin ella, el AP
levanta pero responde **404** a todo.
→ Instalar la UI en `/usr/local/share/wifi-connect/ui` y pasar
`--ui-directory` (el launcher ya lo hace).

### 2. El jar precompilado del backend estaba VIEJO (faltaba `monitoring`)
El `target/cafe-lab-0.0.1-SNAPSHOT.jar` (11-may) tenía **0 clases del contexto
`monitoring`** — se agregó al código después. Resultado: los endpoints
`/telemetry-records` y `/environment-thresholds` no existían → Spring los trataba
como recurso estático → `NoResourceFoundException` (404) → forward a `/error`
(que el filtro deja anónimo) → **401 enmascarando un 404**.
→ Recompilar el jar (`mvn package`). **Importante:** recompilar también antes de
desplegar a la nube.

### 3. Diagnóstico del "401 fantasma"
La autenticación SÍ funcionaba (todos los demás contextos daban 200). El DEBUG de
Spring Security (`Securing` → `Secured` → `Securing /error` → `anonymous`) reveló
que el 401 venía del forward a `/error`, no de la auth. Lección: un 401 en este
backend puede ser un error real enmascarado porque `/error` exige autenticación.

### 4. El edge escuchaba en 127.0.0.1 (inalcanzable por LAN)
Flask `app.run()` por defecto bindea localhost → el ESP32/otros equipos no lo
alcanzan. → Bindear a `0.0.0.0` (`app.py` ya lo hace, configurable con
`EDGE_HOST`/`EDGE_PORT`).

### 5. La cuenta se crea con `POST /api/v1/profiles`, no solo sign-up
Crear el perfil dispara la creación del usuario IAM y los vincula
(`profiles.user_id`). Si solo se hace `/authentication/sign-up`, no hay perfil y
`resolveProfileId()` falla → no se pueden crear suppliers/coffee-lots.

### 6. Validaciones estrictas de value objects (backend)
- `coffee_type`: **"Arábica"** (con tilde), "Robusta" o "Mezcla".
- `status` del lote: **"green"** o **"roasted"** (no "ACTIVE").
- `processing_method`: "Anaeróbico", "Lavado", "Natural", "Honey".
Devuelven un 400 genérico ("No se pudo crear el lote"); revisar los value objects.

### 7. Identidad: `deviceId` (edge) ↔ `coffeeLotId` (backend)
El puente es `device.lot_id` = el `coffeeLotId` numérico. El telemetry POST del
backend valida que el coffeeLot **exista** (no la propiedad), así que el edge
ingesta como cuenta de servicio y el dato se atribuye por el lote.

### 8. mDNS: el hostname del Pi quedó como `raspberrypi`, no `cafelab-edge`
El firmware del ESP32 busca `cafelab-edge.local` por defecto. → O cambiar el
hostname del Pi (`sudo hostnamectl set-hostname cafelab-edge`) o ajustar
`EDGE_HOST`/`EDGE_FALLBACK_IP` en el `.ino`.

### 9. Formato de timestamp
El backend mapea `timestamp` a `LocalDateTime` (sin zona). El edge envía UTC sin
`Z` (`2026-06-06T20:46:27`) — ya manejado en `backend_client.py`.

## Gotchas de entorno (no del proyecto)

- **Pi-hole** ocupaba el puerto 53; `pihole disable` NO libera el puerto (solo
  pausa el bloqueo). → `sudo systemctl stop pihole-FTL`.
- **MySQL local** ya usaba el 3306 → el contenedor MySQL de prueba se corrió sin
  publicar puerto (se comunica por la red Docker `cafelab-net`).
- **Git Bash** mangla rutas tipo `/app` en `docker -w` ("C:/Program Files/Git/app")
  → usar PowerShell o `MSYS_NO_PATHCONV=1`.
- **Java 25** local vs `<java.version>24</java.version>` del pom → recompilar el
  jar dentro de un contenedor JDK 24 (`maven:3.9-eclipse-temurin-24`) evita líos
  con Lombok/Java 25.

## Estado de servicios en el Pi

- `cafelab-edge.service` (systemd) — edge Flask, enabled, en `0.0.0.0:5000`.
- `cafelab-wifi-portal.service` (systemd) — portal cautivo, enabled; abre el AP
  `CafeLab-Setup` solo si no hay WiFi al arrancar.
- Hostname: `raspberrypi` (ajustar a `cafelab-edge` si se usa el firmware por mDNS).

## Pendientes / recomendaciones

- Recompilar el jar del backend en el entorno de despliegue (nube) para incluir
  `monitoring`.
- Parte A (ESP32 real): flashear el firmware y validar lecturas reales.
- Seguridad: el edge guarda la contraseña de la cuenta localmente (el backend usa
  JWT de 7 días sin refresh); cifrar en producción.
- Endurecer el backend: `telemetry-records`/`environment-thresholds` no verifican
  propiedad del lote (solo existencia).
