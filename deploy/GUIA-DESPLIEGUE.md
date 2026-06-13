# Guía de despliegue y pruebas — CafeLab Edge (Raspberry Pi + ESP32)

Runbook paso a paso. **No avances al siguiente paso hasta cumplir la
✅ Validación** de cada uno. El orden es el de *desarrollo* (traer todo arriba de
forma incremental); al final hay una nota sobre el orden real del usuario final.

```
Pi listo → Edge corriendo → mDNS → Edge como servicio → (Sync backend)
        → Portal WiFi → Firmware ESP32 → Prueba end-to-end
```

Necesitas: una Raspberry Pi con WiFi (Pi 3/4/5 o Zero 2 W), un ESP32 + DHT22,
y otra PC en la misma red para probar.

---

## PASO 0 — Preparar la Raspberry Pi

```bash
# Identidad del sistema
cat /etc/os-release | grep PRETTY_NAME    # idealmente: Bookworm o más nuevo
uname -m                                  # aarch64 (64-bit) o armv7l/armv6l
systemctl is-active NetworkManager        # debe decir: active

# Actualizar e instalar utilidades base
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-pip avahi-daemon
```

Si `NetworkManager` **no** está `active` (Raspberry Pi OS Bullseye o anterior):
`sudo raspi-config` → Advanced Options → Network Config → **NetworkManager** →
reiniciar.

> ✅ **Validación:** `systemctl is-active NetworkManager` devuelve `active` y
> anotaste tu arquitectura (`uname -m`). No sigas sin esto: `wifi-connect` lo
> exige.

---

## PASO 1 — Desplegar la app del edge

```bash
# Copia el repo al Pi (git clone de tu remoto, o scp/rsync desde tu PC)
cd ~
git clone <URL-de-tu-repo> edge-clean      # o copia la carpeta edge-clean
cd ~/edge-clean

# Entorno virtual + dependencias
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Ejecutar (escucha en 0.0.0.0:5000)
python app.py
```

En **otra terminal del Pi**:

```bash
curl http://localhost:5000/
# {"status":"ok","service":"edge-clean"}
```

Desde **otra PC en la misma red** (usa la IP del Pi, `hostname -I`):

```bash
curl http://<IP-DEL-PI>:5000/
```

> ✅ **Validación:** ambos `curl` responden `{"status":"ok",...}`. El segundo es
> clave: confirma que el edge es alcanzable desde la LAN (lo que necesita el
> ESP32). Si falla, revisa firewall y que `app.py` escuche en `0.0.0.0`.

Detén el proceso (Ctrl+C) antes de seguir.

---

## PASO 2 — Descubrimiento por nombre (mDNS / Avahi)

Para que el ESP32 encuentre al edge sin IP fija. Detalle en
[`raspberrypi/edge-discovery.md`](raspberrypi/edge-discovery.md).

```bash
sudo hostnamectl set-hostname cafelab-edge
sudo cp ~/edge-clean/deploy/raspberrypi/avahi-cafelab-edge.service \
        /etc/avahi/services/cafelab-edge.service
sudo systemctl restart avahi-daemon
```

Desde **otra PC en la red**:

```bash
ping cafelab-edge.local
```

> ✅ **Validación:** `ping cafelab-edge.local` responde. (El edge no necesita
> estar corriendo para que el ping funcione; eso lo probamos en el paso 3.)

---

## PASO 3 — Correr el edge como servicio (arranque automático)

```bash
# Revisa User y rutas dentro del archivo antes de copiar (por defecto: pi / /home/pi/edge-clean)
sudo cp ~/edge-clean/deploy/raspberrypi/cafelab-edge.service \
        /etc/systemd/system/cafelab-edge.service
sudo systemctl daemon-reload
sudo systemctl enable --now cafelab-edge.service
systemctl status cafelab-edge.service     # debe estar active (running)
```

Desde **otra PC**, combinando con el paso 2:

```bash
curl http://cafelab-edge.local:5000/
# {"status":"ok","service":"edge-clean"}
```

> ✅ **Validación:** `curl http://cafelab-edge.local:5000/` responde desde otra
> máquina. Opcional: `sudo reboot` y vuelve a probar para confirmar que arranca
> solo. Este es el estado "edge productivo en la LAN".

---

## PASO 4 — (Opcional) Sincronización con el backend

Solo si tienes el backend Java corriendo y accesible. Si no, **se puede diferir**
sin afectar el flujo dispositivo↔edge.

1. Crea la cuenta de servicio (una vez) en el backend:

   ```bash
   curl -X POST http://<BACKEND>:8080/api/v1/authentication/sign-up \
     -H "Content-Type: application/json" \
     -d '{"email":"edge@cafelab.com","password":"cambia-esto","..." }'
   ```

2. Edita `cafelab-edge.service`, descomenta y completa los `Environment=` de
   `BACKEND_*`, luego:

   ```bash
   sudo systemctl daemon-reload && sudo systemctl restart cafelab-edge.service
   ```

3. Asegura que el `coffeeLot` exista en el backend. El dispositivo **NO se
   registra a mano**: el ESP32 se auto-anuncia (paso 6) y luego le asignas el
   lote desde `/onboarding` (o por curl con el `deviceId` que viste en el serial):

   ```bash
   curl -X POST http://raspberrypi.local:5000/api/v1/edge/devices/esp32-aabbccddeeff/assign \
     -H "Content-Type: application/json" -d '{"lotId":"7"}'
   ```

4. Fuerza una sincronización (recupera el `api_key` re-anunciando, es idempotente):

   ```bash
   curl -X POST http://raspberrypi.local:5000/api/v1/edge/sync \
     -H "Content-Type: application/json" -H "X-API-Key: <api_key>" \
     -d '{"deviceId":"esp32-aabbccddeeff"}'
   ```

> ✅ **Validación:** `/edge/sync` responde con contadores
> (`readingsPushed`, `thresholdsUpdated`). Si no usas backend aún, salta este
> paso — el edge sigue funcionando standalone.

---

## PASO 5 — Portal cautivo de WiFi (onboarding del usuario)

Detalle en [`raspberrypi/README.md`](raspberrypi/README.md).

> ⚠️ **Antes de empezar:** este paso reconfigura el WiFi del Pi. Si te conectas
> por SSH **sobre WiFi**, ten a mano un cable Ethernet o monitor+teclado: podrías
> perder el acceso durante la prueba.

```bash
# 1a) Instalar el binario wifi-connect según tu arch (uname -m):
#     https://github.com/balena-os/wifi-connect/releases
sudo cp wifi-connect /usr/local/sbin/wifi-connect
sudo chmod +x /usr/local/sbin/wifi-connect

# 1b) Instalar la UI (asset APARTE wifi-connect-ui.tar.gz; sin esto el portal da 404)
curl -sL -o wifi-connect-ui.tar.gz \
  https://github.com/balena-os/wifi-connect/releases/download/v4.11.84/wifi-connect-ui.tar.gz
sudo mkdir -p /usr/local/share/wifi-connect/ui
sudo tar xzf wifi-connect-ui.tar.gz -C /usr/local/share/wifi-connect/ui
ls /usr/local/share/wifi-connect/ui/index.html   # debe existir

# 2) Instalar launcher + servicio
sudo cp ~/edge-clean/deploy/raspberrypi/cafelab-wifi-portal.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/cafelab-wifi-portal.sh
sudo cp ~/edge-clean/deploy/raspberrypi/cafelab-wifi-portal.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cafelab-wifi-portal.service
```

Probar **sin reiniciar** (forzando el portal):

```bash
sudo /usr/local/bin/cafelab-wifi-portal.sh
```

Desde el celular: conéctate a la red **`CafeLab-Setup`** → se abre el portal
(si no, ve a `http://192.168.42.1`) → elige tu WiFi → clave → el Pi se conecta.

```bash
nmcli device status      # wlan0 debe quedar 'connected' a tu red
```

> ✅ **Validación:** aparece `CafeLab-Setup`, conectas tu WiFi desde el portal y
> `nmcli device status` muestra `wlan0` conectado a tu red.

---

## PASO 6 — Flashear el ESP32 (TrackSilo)

Detalle en [`../firmware/tracksilo-esp32/README.md`](../firmware/tracksilo-esp32/README.md).
Firmware **genérico**: no se hornea `device_id` ni `api_key` (auto-enroll).

0. (Para descubrimiento por mDNS) instala el servicio Avahi en el Pi:

   ```bash
   sudo cp ~/edge-clean/deploy/raspberrypi/avahi-cafelab-edge.service \
           /etc/avahi/services/cafelab-edge.service
   sudo systemctl restart avahi-daemon
   avahi-browse -rt _cafelab._tcp     # debe listar el edge
   ```

1. En Arduino IDE: instala el core **ESP32** y las librerías **WiFiManager**,
   **DHT sensor library** (+ Adafruit Unified Sensor) y **ArduinoJson v7**.
2. (Opcional) En la sección CONFIG del `.ino`, ajusta `EDGE_FALLBACK_IP` con la
   IP del Pi (respaldo si mDNS falla). No hay que poner `DEVICE_ID` ni `API_KEY`.
3. Conecta el ESP32 por USB, selecciona placa/puerto y sube el sketch.
4. Abre el Monitor Serie a **115200**. Conecta el cel al AP `TrackSilo-Setup` y
   mete el WiFi del café.
5. El ESP32 se **anuncia solo** → en `/onboarding` aparece "pendiente" →
   **asígnale el lote**.

> ✅ **Validación:** en el Monitor Serie ves `[wifi] conectado`, una línea
> `[mdns] edge por servicio...` (o `usando IP fija`), `[announce] ok` y
> respuestas `201` con `actuatorCommand`.

---

## PASO 7 — Prueba end-to-end

1. Deja el ESP32 enviando lecturas normales → estado `OPTIMAL`, actuador apagado.
2. Provoca humedad alta (sopla sobre el DHT22 o sube `maxHumidity` con
   `PUT /edge/thresholds`). La respuesta debe pasar a `status: DANGER`,
   `actuatorCommand: ACTIVATE` → el LED/deshumedecedor se enciende.
3. Verifica el registro en el edge:

   ```bash
   curl "http://raspberrypi.local:5000/api/v1/edge/readings/latest?deviceId=esp32-aabbccddeeff"
   curl "http://raspberrypi.local:5000/api/v1/edge/actuator-events?deviceId=esp32-aabbccddeeff"
   ```
4. (Si hiciste el paso 4) confirma que la telemetría llegó al backend
   (`GET /api/v1/telemetry-records/coffee-lot/7`).

> ✅ **Validación final:** la humedad alta enciende el actuador, la lectura queda
> en el edge, y (con backend) aparece en la nube.

---

## Nota: orden real del usuario final vs. orden de esta guía

Esta guía está en orden de **desarrollo**. En el **onboarding real** del usuario,
el orden es: (1) Portal WiFi del Pi → (2) login de su cuenta CafeLab en la
pantalla de onboarding del edge *(Parte C, pendiente)* → (3) provisioning del
ESP32. Toda la complejidad técnica de aquí queda escondida detrás de la app.
