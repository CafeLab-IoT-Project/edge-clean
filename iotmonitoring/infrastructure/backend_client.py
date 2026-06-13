import threading
from datetime import datetime, timezone

import requests
from dateutil.parser import parse

from shared.infrastructure.config import BackendConfig


class BackendError(Exception):
    """Base error for backend interactions."""


class BackendUnavailableError(BackendError):
    """Network failure or 5xx; the operation should be retried later."""


class BackendAuthError(BackendError):
    """Sign-in failed (bad service-account credentials)."""


class BackendRejectedError(BackendError):
    """The backend rejected the payload with a 4xx; retrying won't help."""


def _to_backend_timestamp(value) -> str:
    """Render a datetime as a Jackson ``LocalDateTime`` (UTC, no offset).

    The backend maps ``timestamp`` to ``java.time.LocalDateTime``, which does
    not accept a trailing ``Z``/offset, so we normalize to UTC and drop tzinfo.
    """
    if value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        dt = value
    else:
        dt = parse(str(value))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds")


class BackendClient:
    """Outbound client to the CafeLab Java backend (service-account / JWT)."""

    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig.resolve()
        self._token: str | None = None
        self._lock = threading.Lock()

    def _url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}{path}"

    def sign_in(self) -> str:
        try:
            response = requests.post(
                self._url("/api/v1/authentication/sign-in"),
                json={
                    "email": self.config.service_email,
                    "password": self.config.service_password,
                },
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as error:
            raise BackendUnavailableError(f"sign-in request failed: {error}")

        if response.status_code != 200:
            raise BackendAuthError(
                f"sign-in rejected ({response.status_code}): {response.text}"
            )

        token = (response.json() or {}).get("token")
        if not token:
            raise BackendAuthError("sign-in response did not contain a token")

        with self._lock:
            self._token = token
        return token

    def _auth_headers(self) -> dict:
        with self._lock:
            token = self._token
        if token is None:
            token = self.sign_in()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Send an authenticated request, re-signing once on a 401."""
        try:
            response = requests.request(
                method,
                self._url(path),
                headers=self._auth_headers(),
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as error:
            raise BackendUnavailableError(f"{method} {path} failed: {error}")

        if response.status_code == 401:
            self.sign_in()
            try:
                response = requests.request(
                    method,
                    self._url(path),
                    headers=self._auth_headers(),
                    timeout=self.config.timeout_seconds,
                    **kwargs,
                )
            except requests.RequestException as error:
                raise BackendUnavailableError(f"{method} {path} retry failed: {error}")

        return response

    def post_telemetry(self, coffee_lot_id: int, temperature, humidity, recorded_at) -> dict:
        payload = {
            "coffeeLotId": coffee_lot_id,
            "temperature": temperature,
            "humidity": humidity,
            "timestamp": _to_backend_timestamp(recorded_at),
        }
        response = self._request("POST", "/api/v1/telemetry-records", json=payload)

        if response.status_code in (200, 201):
            return response.json()
        if 400 <= response.status_code < 500:
            raise BackendRejectedError(
                f"telemetry rejected ({response.status_code}): {response.text}"
            )
        raise BackendUnavailableError(
            f"telemetry failed ({response.status_code}): {response.text}"
        )

    def get_coffee_lots(self) -> list:
        """List the coffee lots owned by the service account (for lot assignment)."""
        response = self._request("GET", "/api/v1/coffee-lots")
        if response.status_code == 200:
            return response.json() or []
        if 400 <= response.status_code < 500:
            raise BackendRejectedError(
                f"coffee-lots rejected ({response.status_code}): {response.text}"
            )
        raise BackendUnavailableError(
            f"coffee-lots failed ({response.status_code}): {response.text}"
        )

    def get_thresholds(self, coffee_lot_id: int) -> dict | None:
        response = self._request(
            "GET", f"/api/v1/environment-thresholds/coffee-lot/{coffee_lot_id}"
        )
        if response.status_code == 404:
            return None
        if response.status_code == 200:
            return response.json()
        if 400 <= response.status_code < 500:
            raise BackendRejectedError(
                f"thresholds rejected ({response.status_code}): {response.text}"
            )
        raise BackendUnavailableError(
            f"thresholds failed ({response.status_code}): {response.text}"
        )
