"""Tests del onboarding de cuenta (`/api/v1/edge/account`).

El endpoint valida las credenciales contra el backend antes de guardarlas, así
que mockeamos `BackendClient.sign_in` para no salir a la red.
"""

import pytest

from iotmonitoring.infrastructure.backend_client import (
    BackendAuthError,
    BackendClient,
    BackendUnavailableError,
)


def test_get_account_reports_unconfigured_when_no_account(app_client):
    response = app_client.get("/api/v1/edge/account")

    assert response.status_code == 200
    assert response.get_json() == {"configured": False}


def test_post_account_links_and_never_exposes_password(app_client, monkeypatch):
    # Credenciales válidas: sign_in devuelve un token sin tocar la red.
    monkeypatch.setattr(BackendClient, "sign_in", lambda self: "fake-jwt")

    response = app_client.post(
        "/api/v1/edge/account",
        json={
            "email": "edge@cafelab.com",
            "password": "s3cret",
            "backendUrl": "http://backend.test:8080",
        },
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["configured"] is True
    assert body["email"] == "edge@cafelab.com"
    assert body["backendUrl"] == "http://backend.test:8080"

    # El GET refleja la cuenta vinculada pero nunca devuelve la contraseña.
    linked = app_client.get("/api/v1/edge/account").get_json()
    assert linked["configured"] is True
    assert linked["email"] == "edge@cafelab.com"
    assert linked["backendUrl"] == "http://backend.test:8080"
    assert "password" not in linked


def test_post_account_requires_email_and_password(app_client):
    response = app_client.post(
        "/api/v1/edge/account",
        json={"email": "edge@cafelab.com"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "email y password son requeridos"


def test_post_account_rejects_invalid_credentials(app_client, monkeypatch):
    def _raise_auth(self):
        raise BackendAuthError("bad credentials")

    monkeypatch.setattr(BackendClient, "sign_in", _raise_auth)

    response = app_client.post(
        "/api/v1/edge/account",
        json={"email": "edge@cafelab.com", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Credenciales inválidas"
    # No debe quedar cuenta guardada tras un login fallido.
    assert app_client.get("/api/v1/edge/account").get_json() == {"configured": False}


def test_post_account_surfaces_backend_unavailable(app_client, monkeypatch):
    def _raise_unavailable(self):
        raise BackendUnavailableError("connection refused")

    monkeypatch.setattr(BackendClient, "sign_in", _raise_unavailable)

    response = app_client.post(
        "/api/v1/edge/account",
        json={"email": "edge@cafelab.com", "password": "s3cret"},
    )

    assert response.status_code == 502
    assert "No se pudo contactar el backend" in response.get_json()["error"]
