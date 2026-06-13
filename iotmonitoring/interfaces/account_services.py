import os

from flask import Blueprint, Response, jsonify, request

from iotmonitoring.infrastructure.backend_client import (
    BackendAuthError,
    BackendClient,
    BackendUnavailableError,
)
from iotmonitoring.infrastructure.repositories import BackendAccountRepository
from shared.infrastructure.config import BackendConfig
from shared.infrastructure.sync_worker import worker as sync_worker

onboarding_api = Blueprint("onboarding_api", __name__)

DEFAULT_BACKEND_URL = "http://localhost:8080"


@onboarding_api.route("/api/v1/edge/account", methods=["GET"])
def get_account():
    account = BackendAccountRepository.get()
    if account is None:
        return jsonify({"configured": False}), 200
    # Nunca devolvemos la contraseña.
    return jsonify({
        "configured": True,
        "email": account.email,
        "backendUrl": account.base_url,
    }), 200


@onboarding_api.route("/api/v1/edge/account", methods=["POST"])
def set_account():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")
    backend_url = (
        data.get("backendUrl")
        or data.get("backend_url")
        or os.environ.get("BACKEND_BASE_URL", DEFAULT_BACKEND_URL)
    )

    if not email or not password:
        return jsonify({"error": "email y password son requeridos"}), 400

    # Valida las credenciales contra el backend ANTES de guardarlas.
    client = BackendClient(BackendConfig(base_url=backend_url, service_email=email, service_password=password))
    try:
        client.sign_in()
    except BackendAuthError:
        return jsonify({"error": "Credenciales inválidas"}), 401
    except BackendUnavailableError as error:
        return jsonify({"error": f"No se pudo contactar el backend: {error}"}), 502

    BackendAccountRepository.save(backend_url, email, password)
    # Arranca/reinicia el worker para que tome las credenciales recién guardadas.
    sync_worker.start()

    return jsonify({"configured": True, "email": email, "backendUrl": backend_url}), 200


ONBOARDING_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CafeLab Edge — Vincular cuenta</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 22em; margin: 2em auto; padding: 0 1em; }
    label { display: block; margin: .8em 0 .2em; font-weight: 600; }
    input { width: 100%; padding: .5em; box-sizing: border-box; }
    button { margin-top: 1.2em; padding: .6em 1em; width: 100%; }
    #msg { margin-top: 1em; }
    .ok { color: #137333; } .err { color: #b00020; }
  </style>
</head>
<body>
  <h1>Vincular este edge a tu cuenta</h1>
  <form id="f">
    <label>Email</label>
    <input id="email" type="email" required>
    <label>Contraseña</label>
    <input id="password" type="password" required>
    <label>URL del backend</label>
    <input id="backendUrl" type="url" placeholder="http://192.168.1.100:8080">
    <button type="submit">Vincular</button>
  </form>
  <p id="msg"></p>
  <script>
    const f = document.getElementById('f');
    const msg = document.getElementById('msg');
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      msg.textContent = 'Validando...';
      msg.className = '';
      const body = {
        email: document.getElementById('email').value,
        password: document.getElementById('password').value,
        backendUrl: document.getElementById('backendUrl').value || undefined,
      };
      try {
        const r = await fetch('/api/v1/edge/account', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await r.json();
        if (r.ok) {
          msg.textContent = 'Cuenta vinculada: ' + data.email;
          msg.className = 'ok';
        } else {
          msg.textContent = 'Error: ' + (data.error || r.status);
          msg.className = 'err';
        }
      } catch (err) {
        msg.textContent = 'Error de red: ' + err;
        msg.className = 'err';
      }
    });
  </script>
</body>
</html>"""


@onboarding_api.route("/onboarding", methods=["GET"])
def onboarding_page():
    return Response(ONBOARDING_HTML, mimetype="text/html")
