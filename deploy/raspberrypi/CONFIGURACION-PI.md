# Configuración del Raspberry Pi (edge) — referencia y comandos

Resumen de **qué corre en el Pi**, **dónde vive cada archivo** y **los comandos**
que puedes usar para operarlo. Pensado como chuleta para no olvidar qué existe.

> Hostname actual del Pi: **`raspberrypi`** → se llega por `raspberrypi.local`.
> El ESP32 descubre el edge por **servicio mDNS `_cafelab._tcp`** (Avahi), con
> el hostname y la IP fija como respaldo; ver [edge-discovery.md](edge-discovery.md).

---

## 1. Qué corre en el Pi

| Servicio (systemd) | Qué hace | Arranca al boot |
|---|---|---|
| `cafelab-edge.service` | El edge: API Flask en `0.0.0.0:5000` (recibe lecturas del ESP32, sincroniza con el backend) | sí (enabled) |
| `cafelab-wifi-portal.service` | Portal cautivo `CafeLab-Setup`: si al arrancar no hay WiFi, levanta un AP para conectar la Pi desde el celular | sí (enabled) |
| `avahi-daemon` (del sistema) | Publica el Pi por mDNS (`*.local`) para descubrirlo sin IP fija | sí |
| `NetworkManager` (del sistema) | Maneja el WiFi; el portal lo usa para guardar la red | sí |

---

## 2. Dónde vive cada archivo

Los originales están en el repo (`deploy/raspberrypi/`); en el Pi se **copian** a
rutas del sistema. Por eso, tras un `git pull` que cambie un `.service` o el
script, hay que **volver a copiarlos** y recargar systemd (ver §6).

| En el repo | Copiado en el Pi |
|---|---|
| `cafelab-edge.service` | `/etc/systemd/system/cafelab-edge.service` |
| `cafelab-wifi-portal.service` | `/etc/systemd/system/cafelab-wifi-portal.service` |
| `cafelab-wifi-portal.sh` | `/usr/local/bin/cafelab-wifi-portal.sh` |
| `avahi-cafelab-edge.service` | `/etc/avahi/services/cafelab-edge.service` |
| (código del edge) | `/home/pi/edge-clean` |
| (venv de Python) | `/home/pi/edge-clean/.venv` |
| (base de datos SQLite) | `/home/pi/edge-clean/edge_clean.db` |

El binario del portal WiFi (no está en el repo, se descarga de balena):
`/usr/local/sbin/wifi-connect` + UI en `/usr/local/share/wifi-connect/ui`.

---

## 3. Logs — `journalctl`

Todo lo que imprime un servicio systemd va al **journal**. Comando estrella:

```bash
journalctl -u cafelab-edge -f          # EN VIVO (follow), lo que más usarás
```

Más vistas:

```bash
journalctl -u cafelab-edge -n 100      # últimas 100 líneas
journalctl -u cafelab-edge -b          # solo desde el último arranque
journalctl -u cafelab-edge --since "10 min ago"
journalctl -u cafelab-edge --since today
journalctl -u cafelab-edge -p warning  # solo warnings/errores para arriba
journalctl -u cafelab-edge -f | grep -i "push\|failed\|error"
```

Cambia `cafelab-edge` por `cafelab-wifi-portal` para ver el portal.

> Para que los logs salgan **en vivo y completos** (incluyendo las líneas INFO
> tipo `Pushed N reading(s)`), el unit `cafelab-edge.service` trae
> `PYTHONUNBUFFERED=1` y `EDGE_LOG_LEVEL=INFO`. Sube a `DEBUG` si necesitas más.

---

## 4. Controlar un servicio — `systemctl`

```bash
systemctl status cafelab-edge          # ¿corriendo? PID, último error, últimas líneas
sudo systemctl restart cafelab-edge    # reiniciar (tras git pull del código)
sudo systemctl stop cafelab-edge       # detener
sudo systemctl start cafelab-edge      # arrancar
sudo systemctl enable cafelab-edge     # arrancar en cada boot (ya está)
sudo systemctl disable cafelab-edge    # NO arrancar en boot
systemctl is-active cafelab-edge       # active / inactive
systemctl is-enabled cafelab-edge      # enabled / disabled
```

---

## 5. Anatomía de un archivo `.service` (qué es cada cosa)

Ejemplo, `cafelab-edge.service`:

```ini
[Unit]
Description=CafeLab Edge API (Flask)
After=network-online.target          # arranca después de tener red
Wants=network-online.target

[Service]
Type=simple
User=pi                              # corre como el usuario pi
WorkingDirectory=/home/pi/edge-clean # carpeta de trabajo
Environment=EDGE_HOST=0.0.0.0        # variables de entorno (una por línea)
Environment=EDGE_PORT=5000
Environment=PYTHONUNBUFFERED=1
Environment=EDGE_LOG_LEVEL=INFO
ExecStart=/home/pi/edge-clean/.venv/bin/python /home/pi/edge-clean/app.py
Restart=on-failure                   # si crashea, reintenta
RestartSec=5

[Install]
WantedBy=multi-user.target           # se engancha al boot normal
```

Para activar el sync con el backend, descomenta en el unit y completa:
`BACKEND_BASE_URL`, `BACKEND_SERVICE_EMAIL`, `BACKEND_SERVICE_PASSWORD`
(o vincúlalo desde la página `/onboarding` del edge).

---

## 6. Procedimiento al actualizar (git pull en el Pi)

```bash
ssh pi@raspberrypi.local
cd ~/edge-clean && git pull

# Si SOLO cambió código Python:
sudo systemctl restart cafelab-edge

# Si cambió un archivo .service o el script del portal, recópialos:
sudo cp deploy/raspberrypi/cafelab-edge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart cafelab-edge

journalctl -u cafelab-edge -f          # confirmar que arrancó sin errores
```

---

## 7. Portal WiFi (`CafeLab-Setup`)

Detalle completo en [README.md](README.md). Resumen operativo:

- Al arrancar **sin WiFi guardado** → emite la red `CafeLab-Setup` → te conectas
  desde el cel → eliges tu WiFi → la Pi se conecta como cliente.
- Probar a mano (sin reiniciar): `sudo /usr/local/bin/cafelab-wifi-portal.sh`
- Ver el estado del WiFi: `nmcli device status`
- Ver/olvidar redes guardadas:
  ```bash
  nmcli -t -f NAME,TYPE connection show          # listar
  sudo nmcli connection delete "NOMBRE_DE_LA_RED" # olvidar una
  ```

---

## 8. mDNS / descubrimiento

Detalle en [edge-discovery.md](edge-discovery.md). Resumen:

```bash
ping raspberrypi.local                 # ¿resuelve el Pi?
avahi-browse -rt _http._tcp            # ¿se anuncia el servicio HTTP?
sudo hostnamectl set-hostname cafelab-edge   # (opcional) renombrar a cafelab-edge
```

---

## 9. Chequeos rápidos del edge (desde la laptop, misma red)

```bash
curl http://raspberrypi.local:5000/                       # {"status":"ok",...}
curl http://raspberrypi.local:5000/api/v1/edge/sync/status # pendientes de sync
curl http://raspberrypi.local:5000/api/v1/edge/account     # ¿cuenta vinculada?
```

---

## Documentos relacionados
- [README.md](README.md) — instalación del portal WiFi (Parte B).
- [edge-discovery.md](edge-discovery.md) — mDNS/Avahi.
- [../GUIA-DESPLIEGUE.md](../GUIA-DESPLIEGUE.md) — runbook de despliegue completo.
- [../PRUEBA-E2E-ESP32.md](../PRUEBA-E2E-ESP32.md) — prueba ESP32 → edge → backend.
- [../HALLAZGOS.md](../HALLAZGOS.md) — gotchas encontrados en el despliegue.
