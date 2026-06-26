"""Local live dashboard for the Raspberry Pi edge monitor."""

import json
import queue
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request

from iam.application.services import IamApplicationService
from iotmonitoring.application.services import IoTMonitoringApplicationService
from iotmonitoring.infrastructure.repositories import SensorReadingRepository
from shared.infrastructure.events import FLOW, READING, THRESHOLDS, bus

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


def _snapshot_message(requested_id: str | None = None) -> dict:
    return {"kind": "snapshot", "snapshot": build_snapshot(requested_id)}


@dashboard_api.route("/api/v1/edge/dashboard/stream", methods=["GET"])
def dashboard_stream():
    requested_id = request.args.get("deviceId")

    def generate():
        q = bus.subscribe()
        try:
            yield _sse(_snapshot_message(requested_id))
            while True:
                try:
                    event = q.get(timeout=15)
                    events = [event]
                    try:
                        while True:
                            events.append(q.get_nowait())
                    except queue.Empty:
                        pass

                    for item in events:
                        if item.get("type") == FLOW:
                            yield _sse({"kind": "flow", "flow": item.get("payload", {})})

                    if any(item.get("type") in (READING, THRESHOLDS) for item in events):
                        yield _sse(_snapshot_message(requested_id))
                except queue.Empty:
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
  <title>CafeLab Edge - Dashboard</title>
  <style>
    :root {
      --bg: #0d1117; --panel: #171d26; --panel2: #121820; --muted: #93a1b2;
      --text: #f4f7fb; --ok: #2ecc71; --alert: #ef5350; --warn: #f1c40f;
      --line: #2a3442; --in: #4aa3ff; --out: #c9a227;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      background: var(--bg); color: var(--text);
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      min-height: 100vh; padding: 2vh 2vw; display: flex; flex-direction: column;
    }
    header { display: flex; align-items: center; justify-content: space-between; gap: 1em; }
    .brand { font-size: 1.35rem; font-weight: 800; }
    .brand small { color: var(--muted); font-weight: 500; font-size: .9rem; }
    .conn { display: flex; align-items: center; gap: .55em; color: var(--muted); font-size: 1rem; }
    .dot { width: .8em; height: .8em; border-radius: 50%; background: var(--muted); }
    .dot.online { background: var(--ok); box-shadow: 0 0 .6em var(--ok); }
    .dot.offline { background: var(--alert); }

    .stage {
      flex: 1; min-height: 0; display: grid;
      grid-template-columns: minmax(250px, 25vw) minmax(430px, 1fr) minmax(250px, 25vw);
      gap: 1.25vw; margin-top: 2vh;
    }
    .flow-panel, main {
      background: var(--panel); border: 1px solid var(--line); border-radius: 1rem;
      min-height: 0; min-width: 0;
    }
    .flow-panel { padding: 1rem; display: flex; flex-direction: column; overflow: hidden; }
    .flow-head { display: flex; justify-content: space-between; align-items: baseline; gap: .75rem; margin-bottom: .85rem; }
    .flow-title { font-weight: 800; font-size: 1rem; text-transform: uppercase; letter-spacing: .08em; }
    .flow-sub { color: var(--muted); font-size: .82rem; }
    .flow-list { position: relative; flex: 1; display: flex; flex-direction: column; gap: .65rem; overflow: hidden; }
    .flow-empty { color: var(--muted); border: 1px dashed var(--line); border-radius: .75rem; padding: .9rem; font-size: .9rem; }
    .flow-item {
      background: var(--panel2); border: 1px solid var(--line); border-left: .28rem solid var(--in);
      border-radius: .8rem; padding: .68rem; animation: flowFade 6.5s ease forwards;
      box-shadow: 0 1rem 2rem rgba(0,0,0,.18);
      min-width: 0;
    }
    .flow-item.right { border-left-color: var(--out); }
    .flow-row { display: flex; justify-content: space-between; align-items: center; gap: .7rem; margin-bottom: .48rem; min-width: 0; }
    .method { font-weight: 900; color: var(--text); font-size: .78rem; }
    .endpoint {
      color: var(--text); font-family: ui-monospace, Consolas, monospace; font-size: .78rem;
      display: inline-block; max-width: min(18vw, 18rem); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      vertical-align: bottom;
    }
    .code { color: var(--ok); font-weight: 800; font-size: .78rem; }
    .code.err { color: var(--alert); }
    .payload {
      display: grid; grid-template-columns: 1fr; gap: .34rem;
      font-family: ui-monospace, Consolas, monospace; font-size: .68rem; color: #dbe4ef;
      min-width: 0;
    }
    .payload b { color: var(--muted); font-family: system-ui, sans-serif; font-size: .66rem; text-transform: uppercase; letter-spacing: .06em; }
    .payload pre {
      margin: .12rem 0 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      color: #cbd7e5; max-width: 100%;
    }
    @keyframes flowFade {
      0% { opacity: 0; transform: translateY(14px) scale(.985); }
      10% { opacity: 1; transform: translateY(0) scale(1); }
      78% { opacity: 1; transform: translateY(0) scale(1); }
      100% { opacity: 0; transform: translateY(-10px) scale(.985); }
    }

    main { padding: 2.2vh 2vw; display: flex; flex-direction: column; justify-content: center; gap: 2.4vh; }
    .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 1.4vw; }
    .card {
      background: var(--panel2); border: 1px solid var(--line); border-radius: 1rem;
      padding: 3vh 1vw; text-align: center; transition: border-color .3s;
    }
    .card .label { color: var(--muted); font-size: 1.1rem; text-transform: uppercase; letter-spacing: .1em; }
    .card .value {
      font-size: clamp(3.4rem, 6.6vw, 7.6rem); font-weight: 900; line-height: 1.02;
      margin: .08em 0; white-space: nowrap; letter-spacing: 0;
    }
    .card .value.ok { color: var(--ok); }
    .card .value.alert { color: var(--alert); }
    .card .unit { font-size: .32em; color: var(--muted); font-weight: 700; margin-left: .06em; }
    .card .range { color: var(--muted); font-size: 1rem; }
    .thresholds {
      background: var(--panel2); border: 1px solid var(--line); border-radius: 1rem;
      padding: 1.4rem; display: flex; align-items: center; justify-content: center;
      gap: 1.3vw; font-size: 1.22rem; flex-wrap: wrap;
    }
    .thresholds .t-label { color: var(--muted); font-size: .9rem; text-transform: uppercase; letter-spacing: .1em; }
    .thresholds b { color: var(--text); }
    .badge { display: inline-block; padding: .2em .75em; border-radius: 1em; font-size: 1rem; font-weight: 900; }
    .badge.OPTIMAL { background: rgba(46,204,113,.15); color: var(--ok); }
    .badge.WARNING { background: rgba(241,196,15,.15); color: var(--warn); }
    .badge.DANGER  { background: rgba(239,83,80,.15); color: var(--alert); }
    @keyframes pulse { 0% { transform: scale(1);} 30% { transform: scale(1.055);} 100% { transform: scale(1);} }
    .pulse { animation: pulse .5s ease; }
    @keyframes flash { 0% { background: rgba(241,196,15,.45); } 100% { background: var(--panel2); } }
    .flash { animation: flash 1.4s ease; border-color: var(--warn) !important; }

    footer { display: flex; align-items: center; justify-content: space-between; color: var(--muted); font-size: .95rem; margin-top: 1.5vh; }
    .toast {
      position: fixed; top: 2vh; left: 50%; transform: translateX(-50%);
      background: var(--warn); color: #181818; font-weight: 800; padding: .6em 1.4em;
      border-radius: 2em; opacity: 0; transition: opacity .3s; pointer-events: none; font-size: 1rem;
    }
    .toast.show { opacity: 1; }
    .empty { text-align: center; color: var(--muted); font-size: 1.35rem; line-height: 1.6; align-self: center; justify-self: center; }
    .empty code { color: var(--text); }
    .hidden { display: none !important; }
    @media (max-width: 980px) {
      body { padding: 1rem; }
      .stage { grid-template-columns: 1fr; }
      .flow-panel { min-height: 16rem; }
      .cards { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div id="toast" class="toast">Umbrales actualizados</div>

  <header>
    <div class="brand">CafeLab <small id="device">- edge dashboard</small></div>
    <div class="conn"><span id="dot" class="dot"></span><span id="conn">-</span></div>
  </header>

  <section class="stage">
    <aside class="flow-panel">
      <div class="flow-head">
        <div class="flow-title">Entrada al edge</div>
        <div class="flow-sub">ESP32 / UI -> Flask</div>
      </div>
      <div id="edge-flow" class="flow-list"><div class="flow-empty">Esperando requests entrantes...</div></div>
    </aside>

    <main id="main" class="hidden">
      <div class="cards">
        <div class="card" id="card-temp">
          <div class="label">Temperatura</div>
          <div class="value" id="temp">--<span class="unit"> C</span></div>
          <div class="range" id="temp-range">objetivo -</div>
        </div>
        <div class="card" id="card-hum">
          <div class="label">Humedad</div>
          <div class="value" id="hum">--<span class="unit">%</span></div>
          <div class="range" id="hum-range">objetivo -</div>
        </div>
      </div>
      <div class="thresholds" id="thresholds">
        <span class="t-label">Umbrales</span>
        <span>T <b id="th-temp">-</b> C</span>
        <span>H <b id="th-hum">-</b> %</span>
        <span class="badge" id="status">-</span>
      </div>
    </main>

    <aside class="flow-panel">
      <div class="flow-head">
        <div class="flow-title">Sync worker</div>
        <div class="flow-sub">Edge -> Backend</div>
      </div>
      <div id="sync-flow" class="flow-list"><div class="flow-empty">Esperando llamadas al backend...</div></div>
    </aside>
  </section>

  <div id="empty" class="empty hidden">
    No hay dispositivos vinculados a un lote.<br>
    Asigna uno en <code>/onboarding</code>.
  </div>

  <footer>
    <span id="lot">-</span>
    <span id="ago">-</span>
  </footer>

  <script>
    const $ = (id) => document.getElementById(id);
    let lastReadingId = null, lastThKey = null, lastRecordedAt = null;

    const es = new EventSource('/api/v1/edge/dashboard/stream' + location.search);
    es.onmessage = (e) => {
      const message = JSON.parse(e.data);
      if (message.kind === 'flow') addFlow(message.flow || {});
      else render(message.snapshot || message);
    };
    es.onerror = () => setConn(null);

    function setConn(status) {
      const dot = $('dot'), label = $('conn');
      dot.className = 'dot' + (status === 'ONLINE' ? ' online' : status === 'OFFLINE' ? ' offline' : '');
      label.textContent = status || 'reconectando...';
    }

    function fmt(n, d = 1) { return (n === null || n === undefined) ? '--' : Number(n).toFixed(d); }
    function briefValue(value) {
      if (value === null || value === undefined) return '-';
      if (typeof value === 'number' || typeof value === 'boolean') return String(value);
      if (typeof value === 'string') return value.length > 34 ? value.slice(0, 31) + '...' : value;
      return String(value);
    }

    function compact(value) {
      if (value === null || value === undefined || value === '') return '-';
      if (typeof value === 'object' && !Array.isArray(value)) {
        const preferred = [
          'deviceId', 'coffeeLotId', 'temperature', 'humidity', 'timestamp',
          'status', 'readingId', 'actuatorCommand', 'humidityAlert',
          'temperatureAlert', 'thresholdsUpdated', 'readingsPushed',
          'readingsPending', 'id', 'error'
        ];
        const keys = preferred.filter((key) => Object.prototype.hasOwnProperty.call(value, key));
        for (const key of Object.keys(value)) {
          if (!keys.includes(key) && keys.length < 6) keys.push(key);
        }
        const text = keys.slice(0, 6).map((key) => key + '=' + briefValue(value[key])).join(', ');
        return text.length > 170 ? text.slice(0, 167) + '...' : text;
      }
      const text = Array.isArray(value)
        ? '[' + value.slice(0, 3).map(briefValue).join(', ') + (value.length > 3 ? ', ...' : '') + ']'
        : briefValue(value);
      return text.length > 170 ? text.slice(0, 167) + '...' : text;
    }

    function addFlow(flow) {
      const isRight = flow.side === 'right';
      const list = $(isRight ? 'sync-flow' : 'edge-flow');
      const empty = list.querySelector('.flow-empty');
      if (empty) empty.remove();

      const item = document.createElement('article');
      item.className = 'flow-item' + (isRight ? ' right' : '');

      const code = flow.error ? 'ERR' : (flow.status || '-');
      const bad = flow.error || (Number(flow.status) >= 400);
      const requestText = compact(flow.request || (flow.query && Object.keys(flow.query).length ? { query: flow.query } : null));
      const responseText = compact(flow.error ? { error: flow.error } : flow.response);

      item.innerHTML =
        '<div class="flow-row">' +
          '<div><span class="method"></span> <span class="endpoint"></span></div>' +
          '<span class="code"></span>' +
        '</div>' +
        '<div class="payload">' +
          '<div><b>request</b><pre class="req"></pre></div>' +
          '<div><b>response</b><pre class="res"></pre></div>' +
        '</div>';

      item.querySelector('.method').textContent = flow.method || '-';
      item.querySelector('.endpoint').textContent = flow.endpoint || '-';
      const codeEl = item.querySelector('.code');
      codeEl.textContent = code;
      if (bad) codeEl.classList.add('err');
      item.querySelector('.req').textContent = requestText;
      item.querySelector('.res').textContent = responseText;

      list.prepend(item);
      while (list.querySelectorAll('.flow-item').length > 3) list.lastElementChild.remove();
      setTimeout(() => item.remove(), 6600);
    }

    function render(s) {
      if (!s.hasDevice) {
        $('main').classList.add('hidden');
        $('empty').classList.remove('hidden');
        $('device').textContent = '- sin dispositivos con lote';
        setConn(null);
        return;
      }
      $('empty').classList.add('hidden');
      $('main').classList.remove('hidden');

      $('device').textContent = '- ' + s.deviceId;
      $('lot').textContent = 'Lote: ' + (s.lotId ?? '-');
      setConn(s.connectionStatus);

      const th = s.thresholds || {};
      $('th-temp').textContent = fmt(th.minTemperature) + '-' + fmt(th.maxTemperature);
      $('th-hum').textContent = fmt(th.minHumidity) + '-' + fmt(th.maxHumidity);
      $('temp-range').textContent = 'objetivo ' + fmt(th.minTemperature) + '-' + fmt(th.maxTemperature) + ' C';
      $('hum-range').textContent = 'objetivo ' + fmt(th.minHumidity) + '-' + fmt(th.maxHumidity) + ' %';

      const thKey = JSON.stringify(th);
      if (lastThKey !== null && thKey !== lastThKey) {
        flash($('thresholds'));
        showToast();
      }
      lastThKey = thKey;

      const r = s.reading;
      if (!r) {
        $('temp').innerHTML = '--<span class="unit"> C</span>';
        $('hum').innerHTML = '--<span class="unit">%</span>';
        $('status').textContent = 'sin lecturas';
        $('status').className = 'badge';
        return;
      }

      $('temp').innerHTML = fmt(r.temperature) + '<span class="unit"> C</span>';
      $('hum').innerHTML = fmt(r.humidity) + '<span class="unit">%</span>';
      $('temp').className = 'value ' + (r.temperatureAlert ? 'alert' : 'ok');
      $('hum').className = 'value ' + (r.humidityAlert ? 'alert' : 'ok');
      $('status').textContent = r.status;
      $('status').className = 'badge ' + r.status;

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
      if (!lastRecordedAt) { $('ago').textContent = '-'; return; }
      const secs = Math.max(0, Math.round((Date.now() - lastRecordedAt.getTime()) / 1000));
      $('ago').textContent = 'ultima lectura hace ' + secs + ' s';
    }
    setInterval(tickAgo, 1000);
  </script>
</body>
</html>"""
