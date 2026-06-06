# Descubrimiento del edge en la LAN (mDNS / Avahi)

Permite que el ESP32 encuentre al edge por nombre (`cafelab-edge.local`) sin IP
fija, aunque el router cambie la IP por DHCP. En Raspberry Pi OS, **Avahi** ya
viene instalado y publica el hostname automáticamente.

## 1. Poner el hostname del Pi

```bash
sudo hostnamectl set-hostname cafelab-edge
sudo systemctl restart avahi-daemon
```

Desde otra máquina en la misma red, prueba:

```bash
ping cafelab-edge.local
```

Si responde, el ESP32 podrá resolver `cafelab-edge` por mDNS.

## 2. (Opcional) Anunciar el servicio HTTP del edge

Para que el dispositivo pueda *navegar* el servicio `_http._tcp` (no solo el
hostname), instala el archivo de servicio Avahi:

```bash
sudo cp avahi-cafelab-edge.service /etc/avahi/services/cafelab-edge.service
sudo systemctl restart avahi-daemon
```

Verifica el anuncio:

```bash
avahi-browse -rt _http._tcp
```

## 3. El edge debe escuchar en la LAN

El edge debe bindear a `0.0.0.0` (no `127.0.0.1`) para ser alcanzable desde el
ESP32. `app.py` ya lo hace por defecto; se puede ajustar con variables:

```bash
EDGE_HOST=0.0.0.0 EDGE_PORT=5000 python app.py
```

Prueba desde otra máquina de la red:

```bash
curl http://cafelab-edge.local:5000/
# {"status":"ok","service":"edge-clean"}
```

## Notas

- El ESP32 resuelve `cafelab-edge.local` con la librería **ESPmDNS** (ver el
  firmware en `firmware/tracksilo-esp32/`).
- Si por algún motivo mDNS no funciona en tu red, el firmware admite un
  `EDGE_FALLBACK_IP` fijo como respaldo.
