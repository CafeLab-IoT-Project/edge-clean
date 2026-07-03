# Modo kiosko — dashboard a pantalla completa al arrancar

Hace que el Raspberry Pi, al encenderse, abra **automaticamente el dashboard
local del edge** (`http://localhost:5000/dashboard`) en **Chromium a pantalla
completa** (modo kiosko), sin teclado ni raton.

## Por que NO es un servicio de systemd

Un navegador es una app grafica: necesita una sesion X (con `DISPLAY` y
`XAUTHORITY`) y acceso a `seat0`. Un servicio de systemd del sistema arranca al
boot **sin** sesion grafica, asi que un navegador ahi falla o pelea con el
escritorio. La forma correcta y estandar de un kiosko en el Pi es **autoarrancar
Chromium dentro de la sesion del escritorio** que ya hace autologin. Eso da el
mismo comportamiento "daemon" (arranca al boot, se reinicia si crashea) pero
desde dentro de la sesion grafica, que es donde el navegador puede dibujar.

En este Pi ya esta todo el terreno preparado:

- LightDM hace **autologin** del usuario `pi` (`/etc/lightdm/lightdm.conf`:
  `autologin-user=pi`, `autologin-session=rpd-x` -> escritorio **X11**).
- El edge corre aparte como `cafelab-edge.service` y sirve el dashboard.

El kiosko solo engancha un lanzador al **autostart** de esa sesion.

## Piezas

| En el repo | Copiado en el Pi | Que hace |
|---|---|---|
| `cafelab-kiosk.sh` | `/usr/local/bin/cafelab-kiosk.sh` | Espera al edge, apaga el salvapantallas y abre Chromium en kiosko (con reintento). |
| `cafelab-kiosk.desktop` | `/home/pi/.config/autostart/cafelab-kiosk.desktop` | Entrada XDG que lanza el script al iniciar la sesion grafica. |

El script acepta variables opcionales: `KIOSK_URL` (por defecto
`http://localhost:5000/dashboard`), `KIOSK_HEALTH_URL` y `KIOSK_BROWSER`.
Para fijar un dispositivo concreto: `KIOSK_URL=http://localhost:5000/dashboard?deviceId=tracksilo-001`.

## Instalacion en el Pi

Desde el repo ya clonado en el Pi (`~/edge-clean`):

```bash
cd ~/edge-clean

# 1. Script lanzador -> /usr/local/bin (ejecutable)
sudo cp deploy/raspberrypi/cafelab-kiosk.sh /usr/local/bin/cafelab-kiosk.sh
sudo sed -i 's/\r$//' /usr/local/bin/cafelab-kiosk.sh   # por si el repo trajo CRLF de Windows
sudo chmod +x /usr/local/bin/cafelab-kiosk.sh

# 2. Entrada de autostart -> perfil del usuario pi (NO con sudo: es del usuario)
mkdir -p ~/.config/autostart
cp deploy/raspberrypi/cafelab-kiosk.desktop ~/.config/autostart/cafelab-kiosk.desktop

# 3. (Opcional) ocultar el cursor del raton
sudo apt-get install -y unclutter
```

## Probar sin reiniciar

Primero, a mano, para validar Chromium y la pantalla (con el monitor conectado).
Desde **SSH** hay que apuntar a la sesion grafica del Pi:

```bash
DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority /usr/local/bin/cafelab-kiosk.sh
```

Deberia verse el dashboard a pantalla completa en el monitor del Pi. Cortalo con
`Ctrl+C` en el SSH. Si funciona, reinicia para probar el arranque automatico:

```bash
sudo reboot
```

Al volver, el Pi deberia entrar solo al dashboard a pantalla completa.

## Operacion

- **Salir del kiosko** (si hay teclado): `Ctrl+Alt+F2` para ir a otra consola, o
  `Alt+F4` para cerrar Chromium (el script lo reabre a los 3 s; para pararlo del
  todo, borra/renombra el `.desktop` y reinicia la sesion).
- **Cambiar la URL / dispositivo**: edita `KIOSK_URL` en `cafelab-kiosk.sh` (o
  exportala en el `.desktop` con `Exec=env KIOSK_URL=... /usr/local/bin/cafelab-kiosk.sh`).
- **Desactivar el kiosko**: `rm ~/.config/autostart/cafelab-kiosk.desktop` y reinicia.
- **Logs del script**: lo que imprime va al log de la sesion del escritorio
  (`~/.local/share/xorg/` o el journal del usuario). Para depurar, corre el script
  a mano por SSH como arriba y mira la salida.

## Problemas comunes

- **Pantalla en negro / "No Signal" al arrancar**: es el problema de HDMI/EDID, no
  el kiosko. Ver `../HALLAZGOS.md` (hallazgo #10): forzar el modo en `cmdline.txt`.
- **El navegador no abre solo, pero a mano si**: la sesion no proceso el autostart.
  Verifica que el `.desktop` este en `~/.config/autostart/` (del usuario `pi`, sin
  `sudo`) y que la sesion sea la de `pi` (`autologin-user=pi`). Como alternativa,
  en sesiones Wayland (labwc) usa `~/.config/labwc/autostart` con la linea
  `/usr/local/bin/cafelab-kiosk.sh &`.
- **Sale el globo "Restaurar paginas" tras un corte de luz**: ya se mitiga en el
  script limpiando `exit_type`/`exited_cleanly` de las Preferences y con
  `--disable-session-crashed-bubble`.
- **Sale la barra "Traducir esta pagina" (es -> en) y tapa el dashboard**: los
  flags `--disable-features=Translate,TranslateUI` y `--lang=es-ES` ayudan, pero
  el fix definitivo es una **politica de Chromium**. Copia
  `chromium-policies-cafelab.json` a `/etc/chromium/policies/managed/` (Chromium
  de Debian lee las politicas de ahi):

  ```bash
  sudo mkdir -p /etc/chromium/policies/managed
  sudo cp deploy/raspberrypi/chromium-policies-cafelab.json /etc/chromium/policies/managed/cafelab-kiosk.json
  sudo reboot
  ```

  Verifica en `chrome://policy` que aparezca `TranslateEnabled = false`.
- **Pide desbloquear el llavero ("Unlock Default Keyring")**: pasa porque el
  autologin entra sin contrasena, asi que el llavero de GNOME nunca se desbloquea
  y Chromium quiere usarlo. El script lo evita con `--password-store=basic` (el
  dashboard no guarda secretos, no necesita el llavero). Alternativa permanente:
  ponerle contrasena vacia al "Default Keyring" con `seahorse` para que el
  autologin lo abra solo.
- **La pantalla se apaga sola a los minutos**: el script ejecuta
  `xset s off -dpms`; si aun asi se apaga, revisa que corra bajo X11 (`rpd-x`) y no
  Wayland (ahi `xset` no aplica; usa la config del compositor).

## Documentos relacionados

- [CONFIGURACION-PI.md](CONFIGURACION-PI.md) — que corre en el Pi y comandos.
- [../../docs/README-DASHBOARD.md](../../docs/README-DASHBOARD.md) — el dashboard local.
- [../HALLAZGOS.md](../HALLAZGOS.md) — hallazgo #10: HDMI/EDID "No Signal".
