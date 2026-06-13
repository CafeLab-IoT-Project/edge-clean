import logging
import os

from flask import Flask, jsonify

from iam.application.services import IamApplicationService
from iam.interfaces.services import iam_api
from iotmonitoring.interfaces.account_services import onboarding_api
from iotmonitoring.interfaces.services import iotmonitoring_api
from shared.infrastructure.database import init_db
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

first_request = True


@app.before_request
def setup():
    global first_request
    if first_request:
        first_request = False
        init_db()
        IamApplicationService().get_or_create_development_device()
        sync_worker.start()


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
    app.run(host=host, port=port, debug=debug)
