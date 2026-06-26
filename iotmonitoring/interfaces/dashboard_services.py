"""Dashboard local del edge (para el monitor del Raspberry Pi).

Sirve una pantalla en vivo via SSE: muestra la temperatura/humedad actuales y los
umbrales del dispositivo principal (el más recientemente activo CON lote asignado),
y se actualiza en el instante en que llega una lectura o cambian los umbrales
(empujado por el bus de eventos, sin polling).

Rutas:
- GET /dashboard                      -> la página HTML.
- GET /api/v1/edge/dashboard          -> snapshot JSON (debug / fallback).
- GET /api/v1/edge/dashboard/stream   -> stream SSE (text/event-stream).
"""
import json
import queue
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request

from iam.application.services import IamApplicationService
from iotmonitoring.application.services import IoTMonitoringApplicationService
from iotmonitoring.infrastructure.repositories import SensorReadingRepository
from shared.infrastructure.events import bus

dashboard_api = Blueprint("dashboard_api", __name__)

iam_service = IamApplicationService()
monitoring_service = IoTMonitoringApplicationService()
reading_repository = SensorReadingRepository()


def _format_dt(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _assigned_devices() -> list:
    """Solo dispositivos vinculados a un lote (lot_id != null)."""
    return [d for d in iam_service.get_all_devices() if d.lot_id is not None]


def _last_seen(device_id: str) -> datetime | None:
    latest = reading_repository.find_latest_by_device_id(device_id)
    if latest is None or latest.recorded_at is None:
        return None
    recorded = latest.recorded_at
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    return recorded


def _select_device(requested_id: str | None = None):
    """Elige el dispositivo a mostrar: el solicitado (si tiene lote) o, por
    defecto, el más recientemente activo entre los que tienen lote."""
    devices = _assigned_devices()
    if not devices:
        return None
    if requested_id:
        match = next((d for d in devices if d.device_id == requested_id), None)
        if match is not None:
            return match
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return max(devices, key=lambda d: _last_seen(d.device_id) or floor)


def build_snapshot(requested_id: str | None = None) -> dict:
    device = _select_device(requested_id)
    if device is None:
        return {"hasDevice": False}

    device_id = device.device_id
    thresholds = monitoring_service.get_current_thresholds(device_id)
    sensor = monitoring_service.get_sensor_status(device_id)
    latest = monitoring_service.get_latest_reading(device_id)

    reading = None
    if latest is not None:
        r, status, actuator_command, humidity_alert, temperature_alert = latest
        reading = {
            "readingId": r.id,
            "temperature": r.temperature,
            "humidity": r.humidity,
            "status": status,
            "actuatorCommand": actuator_command,
            "humidityAlert": humidity_alert,
            "temperatureAlert": temperature_alert,
            "recordedAt": _format_dt(r.recorded_at),
        }

    return {
        "hasDevice": True,
        "deviceId": device_id,
        "lotId": device.lot_id,
        "connectionStatus": sensor["connection_status"],
        "lastSeenAt": _format_dt(sensor["last_seen_at"]),
        "reading": reading,
        "thresholds": {
            "minTemperature": thresholds.min_temperature,
            "maxTemperature": thresholds.max_temperature,
            "minHumidity": thresholds.min_humidity,
            "maxHumidity": thresholds.max_humidity,
        },
    }


@dashboard_api.route("/api/v1/edge/dashboard", methods=["GET"])
def dashboard_snapshot():
    return jsonify(build_snapshot(request.args.get("deviceId"))), 200


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@dashboard_api.route("/api/v1/edge/dashboard/stream", methods=["GET"])
def dashboard_stream():
    requested_id = request.args.get("deviceId")

    def generate():
        q = bus.subscribe()
        try:
            # Snapshot inicial inmediato (para no esperar al primer evento).
            yield _sse(build_snapshot(requested_id))
            while True:
                try:
                    q.get(timeout=15)
                    # Coalesce: si llegó una ráfaga de eventos, un solo refresco.
                    try:
                        while True:
                            q.get_nowait()
                    except queue.Empty:
                        pass
                    yield _sse(build_snapshot(requested_id))
                except queue.Empty:
                    # Heartbeat (comentario SSE) para mantener viva la conexión.
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@dashboard_api.route("/dashboard", methods=["GET"])
def dashboard_page():
    return Response(DASHBOARD_HTML, mimetype="text/html")


DASHBOARD_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CafeLab Edge — Dashboard</title>
  <style>
    :root {
      --bg: #0e1116; --panel: #171c24; --muted: #8a97a6; --text: #f2f5f8;
      --ok: #2ecc71; --alert: #e74c3c; --warn: #f1c40f; --line: #232b36;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; }
    body {
      background: var(--bg); color: var(--text);
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      display: flex; flex-direction: column; min-height: 100vh; padding: 2.5vh 3vw;
    }
    header { display: flex; align-items: center; justify-content: space-between; gap: 1em; }
    .brand { font-size: 1.4rem; font-weight: 700; letter-spacing: .5px; }
    .brand small { color: var(--muted); font-weight: 400; font-size: .9rem; }
    .conn { display: flex; align-items: center; gap: .5em; color: var(--muted); font-size: 1rem; }
    .dot { width: .8em; height: .8em; border-radius: 50%; background: var(--muted); }
    .dot.online { background: var(--ok); box-shadow: 0 0 .6em var(--ok); }
    .dot.offline { background: var(--alert); }

    main { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 3vh; }
    .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 3vw; }
    .card {
      background: var(--panel); border: 1px solid var(--line); border-radius: 1rem;
      padding: 3vh 2vw; text-align: center; transition: border-color .3s;
    }
    .card .label { color: var(--muted); font-size: 1.5rem; text-transform: uppercase; letter-spacing: 2px; }
    .card .value { font-size: 13vw; font-weight: 800; line-height: 1.05; margin: .1em 0; }
    .card .value.ok { color: var(--ok); }
    .card .value.alert { color: var(--alert); }
    .card .unit { font-size: .35em; color: var(--muted); font-weight: 600; }
    .card .range { color: var(--muted); font-size: 1.2rem; }

    @keyframes pulse { 0% { transform: scale(1);} 30% { transform: scale(1.06);} 100% { transform: scale(1);} }
    .pulse { animation: pulse .5s ease; }

    .thresholds {
      background: var(--panel); border: 1px solid var(--line); border-radius: 1rem;
      padding: 2vh 2vw; display: flex; align-items: center; justify-content: center;
      gap: 3vw; font-size: 1.6rem; transition: background .2s, border-color .2s;
    }
    .thresholds .t-label { color: var(--muted); font-size: 1.1rem; text-transform: uppercase; letter-spacing: 2px; }
    .thresholds b { color: var(--text); }
    @keyframes flash { 0% { background: var(--warn); } 100% { background: var(--panel); } }
    .flash { animation: flash 1.4s ease; border-color: var(--warn) !important; }

    .badge { display: inline-block; padding: .15em .7em; border-radius: 1em; font-size: 1.2rem; font-weight: 700; }
    .badge.OPTIMAL { background: rgba(46,204,113,.15); color: var(--ok); }
    .badge.WARNING { background: rgba(241,196,15,.15); color: var(--warn); }
    .badge.DANGER  { background: rgba(231,76,60,.15); color: var(--alert); }

    footer { display: flex; align-items: center; justify-content: space-between; color: var(--muted); font-size: 1rem; margin-top: 2vh; }
    .toast {
      position: fixed; top: 2vh; left: 50%; transform: translateX(-50%);
      background: var(--warn); color: #1a1a1a; font-weight: 700; padding: .6em 1.4em;
      border-radius: 2em; opacity: 0; transition: opacity .3s; pointer-events: none; font-size: 1.2rem;
    }
    .toast.show { opacity: 1; }
    .empty { text-align: center; color: var(--muted); font-size: 1.8rem; line-height: 1.6; }
    .empty code { color: var(--text); }
    .hidden { display: none !important; }
  </style>
</head>
<body>
  <div id="toast" class="toast">Umbrales actualizados</div>

  <header>
    <div class="brand">CafeLab <small id="device">— edge dashboard</small></div>
    <div class="conn"><span id="dot" class="dot"></span><span id="conn">—</span></div>
  </header>

  <main id="main" class="hidden">
    <div class="cards">
      <div class="card" id="card-temp">
        <div class="label">Temperatura</div>
        <div class="value" id="temp">--<span class="unit">°C</span></div>
        <div class="range" id="temp-range">objetivo —</div>
      </div>
      <div class="card" id="card-hum">
        <div class="label">Humedad</div>
        <div class="value" id="hum">--<span class="unit">%</span></div>
        <div class="range" id="hum-range">objetivo —</div>
      </div>
    </div>
    <div class="thresholds" id="thresholds">
      <span class="t-label">Umbrales</span>
      <span>T <b id="th-temp">—</b> °C</span>
      <span>H <b id="th-hum">—</b> %</span>
      <span class="badge" id="status">—</span>
    </div>
  </main>

  <div id="empty" class="empty hidden">
    No hay dispositivos vinculados a un lote.<br>
    Asigna uno en <code>/onboarding</code>.
  </div>

  <footer>
    <span id="lot">—</span>
    <span id="ago">—</span>
  </footer>

  <script>
    const $ = (id) => document.getElementById(id);
    let lastReadingId = null, lastThKey = null, lastRecordedAt = null;

    const es = new EventSource('/api/v1/edge/dashboard/stream' + location.search);
    es.onmessage = (e) => render(JSON.parse(e.data));
    es.onerror = () => setConn(null); // EventSource reconecta solo

    function setConn(status) {
      const dot = $('dot'), label = $('conn');
      dot.className = 'dot' + (status === 'ONLINE' ? ' online' : status === 'OFFLINE' ? ' offline' : '');
      label.textContent = status || 'reconectando…';
    }

    function fmt(n, d = 1) { return (n === null || n === undefined) ? '--' : Number(n).toFixed(d); }

    function render(s) {
      if (!s.hasDevice) {
        $('main').classList.add('hidden');
        $('empty').classList.remove('hidden');
        $('device').textContent = '— sin dispositivos con lote';
        setConn(null);
        return;
      }
      $('empty').classList.add('hidden');
      $('main').classList.remove('hidden');

      $('device').textContent = '— ' + s.deviceId;
      $('lot').textContent = 'Lote: ' + (s.lotId ?? '—');
      setConn(s.connectionStatus);

      const th = s.thresholds || {};
      $('th-temp').textContent = fmt(th.minTemperature) + '–' + fmt(th.maxTemperature);
      $('th-hum').textContent = fmt(th.minHumidity) + '–' + fmt(th.maxHumidity);
      $('temp-range').textContent = 'objetivo ' + fmt(th.minTemperature) + '–' + fmt(th.maxTemperature) + ' °C';
      $('hum-range').textContent = 'objetivo ' + fmt(th.minHumidity) + '–' + fmt(th.maxHumidity) + ' %';

      // Destello + toast cuando los umbrales cambian.
      const thKey = JSON.stringify(th);
      if (lastThKey !== null && thKey !== lastThKey) {
        flash($('thresholds'));
        showToast();
      }
      lastThKey = thKey;

      const r = s.reading;
      if (!r) {
        $('temp').innerHTML = '--<span class="unit">°C</span>';
        $('hum').innerHTML = '--<span class="unit">%</span>';
        $('status').textContent = 'sin lecturas';
        $('status').className = 'badge';
        return;
      }

      $('temp').innerHTML = fmt(r.temperature) + '<span class="unit">°C</span>';
      $('hum').innerHTML = fmt(r.humidity) + '<span class="unit">%</span>';
      $('temp').className = 'value ' + (r.temperatureAlert ? 'alert' : 'ok');
      $('hum').className = 'value ' + (r.humidityAlert ? 'alert' : 'ok');

      $('status').textContent = r.status;
      $('status').className = 'badge ' + r.status;

      // Pulso cuando llega una lectura nueva.
      if (lastReadingId !== null && r.readingId !== lastReadingId) {
        pulse($('temp')); pulse($('hum'));
      }
      lastReadingId = r.readingId;
      lastRecordedAt = r.recordedAt ? new Date(r.recordedAt) : null;
      tickAgo();
    }

    function pulse(el) { el.classList.remove('pulse'); void el.offsetWidth; el.classList.add('pulse'); }
    function flash(el) { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); }
    let toastTimer = null;
    function showToast() {
      const t = $('toast'); t.classList.add('show');
      clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
    }

    function tickAgo() {
      if (!lastRecordedAt) { $('ago').textContent = '—'; return; }
      const secs = Math.max(0, Math.round((Date.now() - lastRecordedAt.getTime()) / 1000));
      $('ago').textContent = 'última lectura hace ' + secs + ' s';
    }
    setInterval(tickAgo, 1000); // solo cosmético (reloj), no pide datos
  </script>
</body>
</html>"""
