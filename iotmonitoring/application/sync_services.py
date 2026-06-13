import logging

from iam.infrastructure.repositories import DeviceRepository
from iotmonitoring.domain.entities import StorageThresholds
from iotmonitoring.domain.services import StorageThresholdService
from iotmonitoring.infrastructure.backend_client import (
    BackendClient,
    BackendRejectedError,
)
from iotmonitoring.infrastructure.repositories import (
    SensorReadingRepository,
    StorageThresholdsRepository,
)

logger = logging.getLogger(__name__)


class TelemetrySyncService:
    """Orchestrates the edge <-> backend synchronization (outbox + threshold pull).

    The device-facing request path never calls this: readings are answered
    locally and instantly. This service runs in the background and reconciles
    the local SQLite outbox with the backend whenever connectivity is available.
    """

    # Floor to avoid hammering the backend if a tiny value is configured.
    MIN_INTERVAL_SECONDS = 5

    def __init__(self, backend_client: BackendClient | None = None):
        self.backend_client = backend_client or BackendClient()
        self.device_repository = DeviceRepository()
        self.reading_repository = SensorReadingRepository()
        self.thresholds_repository = StorageThresholdsRepository()
        self.threshold_service = StorageThresholdService()
        # Latest sync cadence advertised by the backend (via the thresholds
        # payload). None until a pull sees a value. The worker reads this.
        self.last_interval_seconds: int | None = None

    def _coffee_lot_id_for(self, device_id: str) -> int | None:
        device = self.device_repository.find_by_id(device_id)
        if device is None or device.lot_id is None:
            return None
        try:
            return int(device.lot_id)
        except (TypeError, ValueError):
            logger.warning(
                "Device %s has a non-numeric lot_id (%r); cannot map to coffeeLotId",
                device_id,
                device.lot_id,
            )
            return None

    def push_pending_readings(self, batch_size: int = 50) -> dict:
        """Forward unsynced readings to the backend (outbox drain).

        Stops the batch on the first transient failure so the same rows are
        retried next cycle. Permanently rejected rows (4xx) are marked synced
        to avoid blocking the queue forever.
        """
        readings = self.reading_repository.find_unsynced(batch_size)
        pushed = 0
        skipped = 0

        for reading in readings:
            coffee_lot_id = self._coffee_lot_id_for(reading.device_id)
            if coffee_lot_id is None:
                skipped += 1
                continue

            try:
                self.backend_client.post_telemetry(
                    coffee_lot_id,
                    reading.temperature,
                    reading.humidity,
                    reading.recorded_at,
                )
            except BackendRejectedError as error:
                # e.g. coffee lot does not exist on the backend: retrying is
                # pointless, so drop the row from the outbox.
                logger.warning("Dropping reading %s (rejected): %s", reading.id, error)
                self.reading_repository.mark_synced(reading.id)
                skipped += 1
                continue

            self.reading_repository.mark_synced(reading.id)
            pushed += 1

        return {"pushed": pushed, "skipped": skipped, "examined": len(readings)}

    def pull_thresholds(self, device_id: str) -> StorageThresholds | None:
        """Pull the authoritative thresholds for a device and apply them locally."""
        coffee_lot_id = self._coffee_lot_id_for(device_id)
        if coffee_lot_id is None:
            return None

        payload = self.backend_client.get_thresholds(coffee_lot_id)
        if not payload:
            return None

        # The backend may advertise how often the edge should re-pull. Capture
        # it so the worker can adapt its cadence (configurable from the UI).
        raw_interval = payload.get("syncIntervalSeconds")
        if raw_interval is not None:
            try:
                self.last_interval_seconds = max(
                    self.MIN_INTERVAL_SECONDS, int(raw_interval)
                )
            except (TypeError, ValueError):
                logger.warning("Ignoring non-numeric syncIntervalSeconds: %r", raw_interval)

        try:
            thresholds = self.threshold_service.synchronize(
                device_id,
                payload["minTemperature"],
                payload["maxTemperature"],
                payload["minHumidity"],
                payload["maxHumidity"],
            )
        except (KeyError, ValueError) as error:
            logger.warning(
                "Backend thresholds for device %s are invalid for the edge: %s",
                device_id,
                error,
            )
            return None

        return self.thresholds_repository.save_current(thresholds)

    def pull_all_thresholds(self) -> int:
        updated = 0
        for device in self.device_repository.find_all():
            if device.lot_id is None:
                continue
            if self.pull_thresholds(device.device_id) is not None:
                updated += 1
        return updated
