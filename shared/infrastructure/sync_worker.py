import logging
import threading

from shared.infrastructure.config import BackendConfig

logger = logging.getLogger(__name__)


class SyncWorker:
    """Background daemon thread that drains the outbox and pulls thresholds.

    Decouples the device->edge path (always local, instant) from the
    edge->backend path (eventual, network-dependent).

    The push is event-driven: ``notify()`` wakes the worker as soon as a reading
    arrives, so telemetry reaches the backend within ~a network round trip
    instead of waiting for the poll interval. Threshold pulls stay on the
    periodic heartbeat to avoid an HTTP sweep on every reading.
    """

    def __init__(self, config: BackendConfig | None = None):
        self._explicit_config = config
        self.config = config or BackendConfig.from_env()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    def start(self) -> None:
        # Re-resolve on every start so credentials onboarded after boot
        # (via the edge login page) are picked up.
        self.config = self._explicit_config or BackendConfig.resolve()
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
        self._wake.set()  # break out of the wait immediately

    def notify(self) -> None:
        """Ask the worker to push now (called when a new reading is stored)."""
        self._wake.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        # Imported lazily so the module graph stays clean and the DB is ready.
        from iotmonitoring.application.sync_services import TelemetrySyncService

        service = TelemetrySyncService()
        # Full reconcile once on startup (drain backlog + refresh thresholds).
        self._push(service)
        self._pull(service)

        while not self._stop.is_set():
            woke_by_reading = self._wake.wait(self.config.sync_interval_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break

            self._push(service)
            # Refresh thresholds only on the periodic heartbeat, not on every
            # reading kick (otherwise each reading would trigger an HTTP sweep).
            if not woke_by_reading:
                self._pull(service)

    @staticmethod
    def _push(service) -> None:
        try:
            result = service.push_pending_readings()
            if result["pushed"]:
                logger.info("Pushed %s reading(s) to backend", result["pushed"])
        except Exception as error:  # noqa: BLE001 - worker must never die
            logger.warning("Reading push cycle failed: %s", error)

    @staticmethod
    def _pull(service) -> None:
        try:
            updated = service.pull_all_thresholds()
            if updated:
                logger.info("Pulled thresholds for %s device(s)", updated)
        except Exception as error:  # noqa: BLE001 - worker must never die
            logger.warning("Threshold pull cycle failed: %s", error)


# Shared singleton so app.py and the onboarding endpoint drive the same worker.
worker = SyncWorker()
