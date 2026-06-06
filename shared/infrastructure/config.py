import os


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class BackendConfig:
    """Configuration for the outbound connection to the CafeLab Java backend.

    Values are read from environment variables so the edge can run fully
    standalone (sync disabled) when no service-account credentials are present.
    """

    def __init__(
        self,
        base_url: str,
        service_email: str | None,
        service_password: str | None,
        timeout_seconds: float = 5.0,
        sync_enabled: bool = True,
        sync_interval_seconds: int = 30,
    ):
        self.base_url = base_url
        self.service_email = service_email
        self.service_password = service_password
        self.timeout_seconds = timeout_seconds
        self.sync_interval_seconds = sync_interval_seconds
        # Sync only makes sense when we actually have credentials to sign in.
        self.sync_enabled = sync_enabled and bool(service_email and service_password)

    @classmethod
    def from_env(cls) -> "BackendConfig":
        return cls(
            base_url=os.environ.get("BACKEND_BASE_URL", "http://localhost:8080"),
            service_email=os.environ.get("BACKEND_SERVICE_EMAIL"),
            service_password=os.environ.get("BACKEND_SERVICE_PASSWORD"),
            timeout_seconds=float(os.environ.get("BACKEND_TIMEOUT_SECONDS", "5")),
            sync_enabled=_as_bool(os.environ.get("BACKEND_SYNC_ENABLED"), default=True),
            sync_interval_seconds=int(os.environ.get("BACKEND_SYNC_INTERVAL_SECONDS", "30")),
        )
