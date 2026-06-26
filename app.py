import logging
import os

from flask import Flask, jsonify, request

from iam.application.services import IamApplicationService
from iam.interfaces.services import iam_api
from iotmonitoring.interfaces.account_services import onboarding_api
from iotmonitoring.interfaces.dashboard_services import dashboard_api
from iotmonitoring.interfaces.services import iotmonitoring_api
from shared.infrastructure.database import init_db
from shared.infrastructure.events import FLOW, bus
from shared.infrastructure.sync_worker import worker as sync_worker

# Emit INFO logs (sync pushes/pulls) to stderr -> systemd journal.
# Override with EDGE_LOG_LEVEL=DEBUG/WARNING.
logging.basicConfig(
    level=os.environ.get("EDGE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = Flask(__name__)
app.register_blueprint(iam_api)
app.register_blueprint(iotmonitoring_api)
app.register_blueprint(onboarding_api)
app.register_blueprint(dashboard_api)

first_request = True


def _json_request_payload():
    if request.is_json:
        return request.get_json(silent=True) or {}
    if request.form:
        return request.form.to_dict(flat=True)
    return None


def _json_response_payload(response):
    if response.is_streamed or response.direct_passthrough:
        return None
    if response.mimetype == "application/json":
        return response.get_json(silent=True)
    return None


def _should_trace_request() -> bool:
    path = request.path
    if path.startswith("/api/v1/edge/dashboard") or path == "/dashboard":
        return False
    return path.startswith("/api/v1/edge") or path.startswith("/api/v1/iam")


@app.before_request
def setup():
    global first_request
    if first_request:
        first_request = False
        init_db()
        IamApplicationService().get_or_create_development_device()
        sync_worker.start()


@app.after_request
def publish_request_flow(response):
    if _should_trace_request():
        bus.publish(
            FLOW,
            {
                "side": "left",
                "source": "edge endpoint",
                "method": request.method,
                "endpoint": request.path,
                "query": request.args.to_dict(flat=True),
                "request": _json_request_payload(),
                "status": response.status_code,
                "response": _json_response_payload(response),
            },
        )
    return response


@app.route("/", methods=["GET"])
def status():
    return jsonify({"status": "ok", "service": "edge-clean"}), 200


if __name__ == "__main__":
    # Bind to 0.0.0.0 so devices on the LAN (the ESP32) can reach the edge.
    # 127.0.0.1 would only be reachable from the Pi itself.
    host = os.environ.get("EDGE_HOST", "0.0.0.0")
    port = int(os.environ.get("EDGE_PORT", "5000"))
    # Disable debug/reloader when running under systemd (EDGE_DEBUG=0).
    debug = os.environ.get("EDGE_DEBUG", "1") == "1"
    # threaded=True: el stream SSE del dashboard mantiene una conexión abierta;
    # sin hilos bloquearía el resto de requests (lecturas, etc.).
    app.run(host=host, port=port, debug=debug, threaded=True)
