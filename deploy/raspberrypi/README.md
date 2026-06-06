# Onboarding del edge — Parte B: WiFi por portal cautivo (Raspberry Pi)

Permite que un usuario no técnico conecte la Raspberry Pi (el edge) a su WiFi
desde el celular, sin teclado ni pantalla en la Pi. Usa
[balena wifi-connect](https://github.com/balena-os/wifi-connect).

## Cómo funciona

```
Arranca la Pi → ¿hay WiFi guardado?
  Sí → no hace nada (sigue el arranque normal del edge)
  No → emite la red "CafeLab-Setup" + portal cautivo
       El usuario se conecta con el cel → elige su WiFi → escribe la clave
       La Pi guarda las credenciales (NetworkManager) y se conecta como cliente
```

## Prerrequisito: NetworkManager

`wifi-connect` **requiere NetworkManager** (no `dhcpcd`). Verifica:

```bash
cat /etc/os-release          # idealmente Bookworm o más nuevo
systemctl is-active NetworkManager   # debe decir: active
uname -m                     # arquitectura: aarch64 (64-bit) o armv7l/armv6l (32-bit)
```

Si NetworkManager no está activo (Raspberry Pi OS Bullseye o anterior), actívalo
con `sudo raspi-config` → Advanced Options → Network Config → NetworkManager, y
reinicia.

## Instalación

1. **Descargar el binario** de la [página de releases](https://github.com/balena-os/wifi-connect/releases)
   según `uname -m` (aarch64 → asset `aarch64`; armv7l/armv6l → asset `rpi`),
   descomprimir y copiar:

   ```bash
   sudo cp wifi-connect /usr/local/sbin/wifi-connect
   sudo chmod +x /usr/local/sbin/wifi-connect
   ```

   > ⚠️ **Importante:** el tarball del binario **NO incluye la web del portal**.
   > La UI viene en un asset aparte, `wifi-connect-ui.tar.gz`. Si solo instalas
   > el binario, el portal responde **404**. Instala también la UI (usa la misma
   > versión que el binario, p. ej. `v4.11.84`):
   >
   > ```bash
   > curl -sL -o wifi-connect-ui.tar.gz \
   >   https://github.com/balena-os/wifi-connect/releases/download/v4.11.84/wifi-connect-ui.tar.gz
   > sudo mkdir -p /usr/local/share/wifi-connect/ui
   > sudo tar xzf wifi-connect-ui.tar.gz -C /usr/local/share/wifi-connect/ui
   > ls /usr/local/share/wifi-connect/ui/index.html   # verificar
   > ```
   >
   > El launcher pasa `--ui-directory /usr/local/share/wifi-connect/ui`
   > automáticamente (configurable con `CAFELAB_UI_DIR`).

2. **Instalar el launcher y el servicio** (desde esta carpeta, copiada a la Pi):

   ```bash
   sudo cp cafelab-wifi-portal.sh /usr/local/bin/cafelab-wifi-portal.sh
   sudo chmod +x /usr/local/bin/cafelab-wifi-portal.sh
   sudo cp cafelab-wifi-portal.service /etc/systemd/system/cafelab-wifi-portal.service
   sudo systemctl daemon-reload
   sudo systemctl enable cafelab-wifi-portal.service
   ```

## Probar (sin reiniciar)

Olvida la red actual para forzar el portal y corre el launcher a mano:

```bash
sudo /usr/local/bin/cafelab-wifi-portal.sh
```

Desde el celular: aparece la red **CafeLab-Setup** → conéctate → debería abrirse
el portal solo (si no, ve a `http://192.168.42.1`) → elige tu WiFi → clave →
la Pi se conecta. Verifica con:

```bash
nmcli device status        # wlan0 debe quedar 'connected' a tu red
```

## Personalización (variables de entorno)

| Variable | Default | Descripción |
|---|---|---|
| `CAFELAB_PORTAL_SSID` | `CafeLab-Setup` | Nombre de la red de configuración |
| `CAFELAB_PORTAL_PASSPHRASE` | (vacío = abierta) | Clave WPA2 del portal (≥ 8 chars) |
| `CAFELAB_WIFI_CONNECT` | `/usr/local/sbin/wifi-connect` | Ruta al binario |

Para fijarlas en el servicio, agrega líneas `Environment=...` en el `.service`.

## Notas

- Un solo radio WiFi no puede ser AP y cliente a la vez: por eso el flujo es
  secuencial (AP → guarda credenciales → cliente).
- Esto resuelve **solo la parte B** (edge → WiFi). Las partes A (ESP32 ↔ edge,
  pairing + API key) y C (vincular el dispositivo a la cuenta del usuario) van
  encima de esto.
