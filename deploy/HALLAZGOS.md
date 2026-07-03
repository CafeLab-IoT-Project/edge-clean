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
El descubrimiento principal del firmware es por **servicio** `_cafelab._tcp`
(`EDGE_SERVICE = "cafelab"`), que Avahi anuncia independientemente del hostname.
Como respaldo, el firmware resuelve por hostname `raspberrypi` (`EDGE_HOST`) y
luego por `EDGE_FALLBACK_IP`. → Basta con instalar el servicio Avahi en el Pi; si
se prefiere el respaldo por hostname, alinea `EDGE_HOST`/`EDGE_FALLBACK_IP` del
`.ino` con el hostname/IP reales del Pi.

### 9. Formato de timestamp
El backend mapea `timestamp` a `LocalDateTime` (sin zona). El edge envía UTC sin
`Z` (`2026-06-06T20:46:27`) — ya manejado en `backend_client.py`.

### 10. Monitor HDMI en "No Signal" tras desconectar/reconectar (Pi 4, KMS) — 2026-07-03
El monitor (uno antiguo) mostraba **"No Signal"** aunque el Pi tenía corriente.
Curioso: funcionaba **una vez** tras un reinicio con el cable puesto, pero al
**desenchufar y volver a enchufar** el HDMI se quedaba en "No Signal".

Diagnóstico (por SSH, sin depender de la pantalla):

```bash
cat /proc/device-tree/model                    # Raspberry Pi 4 Model B
grep -Ei 'hdmi|vc4-kms' /boot/firmware/config.txt   # dtoverlay=vc4-kms-v3d (driver KMS)
# El conector reporta "connected" (el pin HPD sí se detecta)...
for c in /sys/class/drm/card*-HDMI-A-*/status; do echo "$c: $(cat $c)"; done
sudo cat /sys/class/drm/card1-HDMI-A-1/edid | wc -c   # ...pero EDID = 0 bytes
dmesg | grep -iE 'edid|hdmi'                    # "EDID block 0 is all zeroes"
```

**Causa:** el conector detecta el *hotplug* (pin HPD) y aparece `connected`, pero
la **lectura del EDID falla** (`edid` = 0 bytes / `EDID block 0 is all zeroes`).
El EDID viaja por los pines DDC/I²C, separados del HPD y de los datos de vídeo
(TMDS). Sin EDID, el driver KMS cae a modos VESA genéricos (1024x768, 800x600…) y
en un *replug* a menudo no fija ningún modo → "No Signal". Que funcione **una vez**
por arranque en frío y nunca al reenchufar es la firma de un **cable/adaptador
HDMI marginal o un conector flojo** (líneas DDC intermitentes; el vídeo y el HPD
sí funcionan).

**Importante (Pi 4/5 = KMS):** con el driver `vc4-kms-v3d`, los viejos trucos
`hdmi_force_hotplug` y `config_hdmi_boost` de `config.txt` **no hacen nada**. El
equivalente es forzar el modo por parámetro de kernel en `cmdline.txt`.

**Solución:**
1. Primero lo físico (causa raíz más común): **cambiar el cable HDMI** y, si hay
   adaptador micro-HDMI→HDMI en el Pi 4, cambiarlo también; reasentar ambos
   extremos. Usar el puerto **HDMI0** (el más cercano al USB-C = `HDMI-A-1`).
2. Workaround robusto: **forzar un modo ignorando el EDID** en
   `/boot/firmware/cmdline.txt` (una sola línea, sin saltos):

   ```bash
   sudo cp -n /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak
   # Quita cualquier video= previo de HDMI-A-1 y fija 1024x768 (seguro en monitores viejos)
   sudo sed -i -E 's/ ?video=HDMI-A-1:[^ ]*//g; s/$/ video=HDMI-A-1:1024x768@60D/' /boot/firmware/cmdline.txt
   cat /boot/firmware/cmdline.txt          # verificar: UNA línea, termina en video=HDMI-A-1:1024x768@60D
   sudo reboot
   ```

   El sufijo **`D`** = *force* (usa ese modo aunque no lea el EDID). Elegir la
   resolución nativa del monitor si se conoce (17"/19" 5:4 → `1280x1024@60D`;
   4:3 antiguo → `1024x768@60D`). Confirmado ✅: tras esto el *replug* recupera
   imagen y `dmesg` ya no repite `EDID block 0 is all zeroes` en ese arranque.

> Nota: para este proyecto el monitor no es imprescindible — el edge corre
> *headless* por SSH (y con VNC si se quiere escritorio remoto).

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
- Hostname: `raspberrypi`. El firmware descubre el edge por servicio mDNS
  (`_cafelab._tcp`), así que no depende de renombrar el host; el respaldo por
  hostname del `.ino` (`EDGE_HOST`) ya apunta a `raspberrypi`.

## Pendientes / recomendaciones

- Recompilar el jar del backend en el entorno de despliegue (nube) para incluir
  `monitoring`.
- Parte A (ESP32 real): flashear el firmware y validar lecturas reales.
- Seguridad: el edge guarda la contraseña de la cuenta localmente (el backend usa
  JWT de 7 días sin refresh); cifrar en producción.
- Endurecer el backend: `telemetry-records`/`environment-thresholds` no verifican
  propiedad del lote (solo existencia).
