from flask import Flask, jsonify

from iam.application.services import IamApplicationService
from iam.interfaces.services import iam_api
from iotmonitoring.interfaces.services import iotmonitoring_api
from shared.infrastructure.database import init_db

app = Flask(__name__)
app.register_blueprint(iam_api)
app.register_blueprint(iotmonitoring_api)

first_request = True


@app.before_request
def setup():
    global first_request
    if first_request:
        first_request = False
        init_db()
        IamApplicationService().get_or_create_development_device()


@app.route("/", methods=["GET"])
def status():
    return jsonify({"status": "ok", "service": "edge-clean"}), 200


if __name__ == "__main__":
    app.run(debug=True)
