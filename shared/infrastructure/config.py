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
        timeout_seconds: float = 10.0,
        sync_enabled: bool = True,
        sync_interval_seconds: int = 10,
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
            timeout_seconds=float(os.environ.get("BACKEND_TIMEOUT_SECONDS", "10")),
            sync_enabled=_as_bool(os.environ.get("BACKEND_SYNC_ENABLED"), default=True),
            sync_interval_seconds=int(os.environ.get("BACKEND_SYNC_INTERVAL_SECONDS", "10")),
        )

    @classmethod
    def resolve(cls) -> "BackendConfig":
        """Prefer the account onboarded via the edge UI; fall back to env vars.

        Lets a user link the edge to their CafeLab account from the onboarding
        page instead of setting BACKEND_SERVICE_* by hand.
        """
        account = None
        try:
            from iotmonitoring.infrastructure.repositories import BackendAccountRepository

            account = BackendAccountRepository.get()
        except Exception:
            # DB not ready yet (e.g. before init_db) -> just use env.
            account = None

        if account is None:
            return cls.from_env()

        return cls(
            base_url=account.base_url,
            service_email=account.email,
            service_password=account.password,
            timeout_seconds=float(os.environ.get("BACKEND_TIMEOUT_SECONDS", "10")),
            sync_enabled=_as_bool(os.environ.get("BACKEND_SYNC_ENABLED"), default=True),
            sync_interval_seconds=int(os.environ.get("BACKEND_SYNC_INTERVAL_SECONDS", "10")),
        )
