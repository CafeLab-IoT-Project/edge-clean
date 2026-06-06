import logging
import threading

from shared.infrastructure.config import BackendConfig

logger = logging.getLogger(__name__)


class SyncWorker:
    """Background daemon thread that drains the outbox and pulls thresholds.

    Decouples the device->edge path (always local, instant) from the
    edge->backend path (eventual, network-dependent).
    """

    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig.from_env()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.config.sync_enabled:
            logger.info(
                "Backend sync disabled (no BACKEND_SERVICE_EMAIL/PASSWORD); "
                "running edge standalone"
            )
            return
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="edge-sync-worker", daemon=True
        )
        self._thread.start()
        logger.info(
            "Edge sync worker started (interval=%ss, backend=%s)",
            self.config.sync_interval_seconds,
            self.config.base_url,
        )

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # Imported lazily so the module graph stays clean and the DB is ready.
        from iotmonitoring.application.sync_services import TelemetrySyncService

        service = TelemetrySyncService()
        while not self._stop.is_set():
            self._run_once(service)
            self._stop.wait(self.config.sync_interval_seconds)

    @staticmethod
    def _run_once(service) -> None:
        try:
            result = service.push_pending_readings()
            if result["pushed"]:
                logger.info("Pushed %s reading(s) to backend", result["pushed"])
        except Exception as error:  # noqa: BLE001 - worker must never die
            logger.warning("Reading push cycle failed: %s", error)

        try:
            updated = service.pull_all_thresholds()
            if updated:
                logger.info("Pulled thresholds for %s device(s)", updated)
        except Exception as error:  # noqa: BLE001 - worker must never die
            logger.warning("Threshold pull cycle failed: %s", error)
