from flask import Blueprint, jsonify, request

from iam.application.services import IamApplicationService

iam_api = Blueprint("iam_api", __name__, url_prefix="/api/v1/iam")
iam_service = IamApplicationService()


def _request_json() -> dict:
    return request.get_json(silent=True) or {}


def _get_device_id(data: dict) -> str | None:
    return data.get("device_id") or data.get("deviceId")


def _get_lot_id(data: dict) -> str | None:
    return data.get("lot_id") or data.get("lotId")


def _format_created_at(device) -> str:
    created_at = device.created_at.isoformat()
    return created_at if created_at.endswith("Z") else f"{created_at}Z"


def _device_resource(device: object, include_api_key: bool = False) -> dict:
    resource = {
        "device_id": device.device_id,
        "lot_id": device.lot_id,
        "created_at": _format_created_at(device),
    }
    if include_api_key:
        resource["api_key"] = device.api_key
    return resource


def authenticate_request():
    data = _request_json()
    device_id = _get_device_id(data)
    api_key = request.headers.get("X-API-Key")
    if not device_id or not api_key:
        return jsonify({"error": "Missing device_id or X-API-Key"}), 401
    if not iam_service.authenticate(device_id, api_key):
        return jsonify({"error": "Invalid device_id or API key"}), 401
    return None


def authenticateRequest():
    return authenticate_request()


@iam_api.route("/devices", methods=["POST"])
def register_device():
    data = _request_json()
    device_id = _get_device_id(data)
    lot_id = _get_lot_id(data)

    try:
        device = iam_service.register_device(device_id, lot_id)
        return jsonify(_device_resource(device, include_api_key=True)), 201
    except ValueError as error:
        status = 409 if str(error) == "device_id is already registered" else 400
        return jsonify({"error": str(error)}), status


@iam_api.route("/devices/announce", methods=["POST"])
def announce_device():
    """Phone-home self-enrollment: the device introduces itself by id (its MAC).

    Returns its api_key (generated on first contact) so the firmware can
    authenticate subsequent readings without being pre-flashed.
    """
    data = _request_json()
    device_id = _get_device_id(data)
    if not device_id:
        return jsonify({"error": "Missing device_id"}), 400

    try:
        device = iam_service.announce_device(device_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    resource = _device_resource(device, include_api_key=True)
    resource["assigned"] = device.lot_id is not None
    return jsonify(resource), 200


@iam_api.route("/authentication", methods=["POST"])
def authenticate_device():
    auth_result = authenticate_request()
    if auth_result:
        return auth_result

    data = _request_json()
    return jsonify({
        "authenticated": True,
        "device_id": _get_device_id(data),
    }), 200


@iam_api.route("/devices", methods=["GET"])
def list_all_devices():
    try:
        devices = iam_service.get_all_devices()
        resources = [_device_resource(device, include_api_key=True) for device in devices]
        return jsonify({"devices": resources}), 200
    except Exception as error:
        return jsonify({"error": f"Devices could not be listed: {error}"}), 500