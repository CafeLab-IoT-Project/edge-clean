# Descubrimiento del edge en la LAN (mDNS / Avahi)

Permite que el ESP32 encuentre al edge sin IP fija. El método **principal y más
fiable** es por **servicio mDNS** (`_cafelab._tcp`) que publica Avahi en el Pi —
no por hostname, porque `MDNS.queryHost()` en ESP32 es poco confiable.

El firmware resuelve el edge en cascada (ver `resolveEdge()` en el `.ino`):

1. **Servicio mDNS** `_cafelab._tcp` → `MDNS.queryService("cafelab","tcp")` (preferido).
2. **Hostname mDNS** `raspberrypi` → `MDNS.queryHost("raspberrypi")` (respaldo).
3. **IP fija** `EDGE_FALLBACK_IP` → último respaldo si mDNS falla.

> El hostname del Pi se mantiene como **`raspberrypi`** (no se renombró a
> `cafelab-edge`). Su nombre mDNS es `raspberrypi.local`.

## 1. Anunciar el servicio del edge (lo importante)

Instala el archivo de servicio Avahi (anuncia `_cafelab._tcp` **y** `_http._tcp`
en el puerto 5000) y reinicia Avahi:

```bash
sudo cp ~/edge-clean/deploy/raspberrypi/avahi-cafelab-edge.service \
        /etc/avahi/services/cafelab-edge.service
sudo systemctl restart avahi-daemon
```

Verifica el anuncio (en el Pi o cualquier Linux de la LAN):

```bash
avahi-browse -rt _cafelab._tcp
# Debe listar "CafeLab Edge on raspberrypi" con su IP y puerto 5000
```

Si eso aparece, el lado del Pi está listo y el ESP32 lo descubrirá por servicio.

## 2. El edge debe escuchar en la LAN

El edge debe bindear a `0.0.0.0` (no `127.0.0.1`) para ser alcanzable desde el
ESP32. `app.py` ya lo hace por defecto; se puede ajustar con variables:

```bash
EDGE_HOST=0.0.0.0 EDGE_PORT=5000 python app.py
```

Prueba desde otra máquina de la red (por IP o por hostname):

```bash
curl http://raspberrypi.local:5000/
# {"status":"ok","service":"edge-clean"}
```

## 3. (Opcional) IP estable

Para que el respaldo `EDGE_FALLBACK_IP` del firmware no se quede viejo, **reserva
la IP del Pi en el router** (DHCP estático por su MAC). Así, aunque el mDNS
fallara, la IP fija siempre apunta bien.

## Por qué falla el mDNS en ESP32 (gotchas)

- `MDNS.queryHost()` es **poco fiable** resolviendo el `.local` de otro equipo →
  por eso preferimos `queryService`.
- Redes **guest / hotspot / con aislamiento de cliente** bloquean el multicast
  mDNS (puerto 5353). El ESP32 y el Pi deben estar en la **misma WiFi normal**.
- `avahi-daemon` debe estar **activo** en el Pi y el servicio instalado (paso 1).
- En el firmware, `MDNS.begin()` se llama **después** de conectar el WiFi (ya es así).

## Notas

- El ESP32 descubre el edge con la librería **ESPmDNS** (ver `resolveEdge()` en
  `firmware/tracksilo-esp32/`). El log serial indica qué método resolvió:
  `[mdns] edge por servicio...` / `por host...` / `usando IP fija`.
