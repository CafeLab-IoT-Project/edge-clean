#!/usr/bin/env bash
# CafeLab Edge - lanzador del kiosko
# Abre el dashboard local del edge en Chromium a pantalla completa (modo kiosko).
#
# IMPORTANTE: esto arranca DENTRO de la sesion grafica del usuario (autologin de
# 'pi' via LightDM), NO como servicio de systemd. Un navegador necesita la sesion
# X (DISPLAY/XAUTHORITY); un daemon del sistema no la tiene. Ver KIOSK.md.
#
# Variables opcionales (se pueden exportar antes de llamarlo):
#   KIOSK_URL         URL a mostrar (def: http://localhost:5000/dashboard)
#   KIOSK_HEALTH_URL  endpoint que debe responder antes de abrir (def: http://localhost:5000/)
#   KIOSK_BROWSER     comando del navegador (def: chromium)
set -u

KIOSK_URL="${KIOSK_URL:-http://localhost:5000/dashboard}"
HEALTH_URL="${KIOSK_HEALTH_URL:-http://localhost:5000/}"
BROWSER="${KIOSK_BROWSER:-chromium}"

# Sesion X11: si no viene del entorno (caso autologin), asume el display :0.
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

log() { echo "$(date '+%F %T') cafelab-kiosk: $*"; }

# 1. Evitar que la pantalla se apague o entre el salvapantallas (X11).
if command -v xset >/dev/null 2>&1; then
  xset s off     || true
  xset s noblank || true
  xset -dpms     || true
fi

# 2. Ocultar el cursor del raton si 'unclutter' esta instalado (opcional).
if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0.5 -root &
fi

# 3. Esperar a que el edge responda (arranca en paralelo como servicio systemd).
log "Esperando al edge en $HEALTH_URL ..."
until curl -fs -o /dev/null "$HEALTH_URL"; do
  sleep 2
done
log "Edge arriba. Abriendo $KIOSK_URL con $BROWSER"

# 4. Limpiar el flag de 'cierre inesperado' para que Chromium NO muestre el globo
#    'Restaurar paginas' tras un corte de luz.
PREFS="$HOME/.config/chromium/Default/Preferences"
if [ -f "$PREFS" ]; then
  sed -i 's/"exit_type":"[^"]*"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' "$PREFS" || true
fi

# 5. Lanzar Chromium en modo kiosko. Bucle de reintento: si el navegador se
#    cierra o crashea, se vuelve a abrir (comportamiento tipo daemon).
while true; do
  "$BROWSER" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=Translate \
    --no-first-run \
    --check-for-update-interval=31536000 \
    --autoplay-policy=no-user-gesture-required \
    "$KIOSK_URL"
  log "Chromium termino (codigo $?). Reintentando en 3s..."
  sleep 3
done
