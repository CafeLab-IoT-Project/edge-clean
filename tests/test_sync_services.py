from datetime import datetime, timezone

from iam.infrastructure.repositories import DeviceRepository
from iotmonitoring.application.services import IoTMonitoringApplicationService
from iotmonitoring.application.sync_services import TelemetrySyncService
from iotmonitoring.infrastructure.backend_client import BackendRejectedError
from iotmonitoring.infrastructure.repositories import (
    SensorReadingRepository,
    StorageThresholdsRepository,
)

DEVICE_ID = "tracksilo-001"


class SuccessfulBackendClient:
    def __init__(self):
        self.telemetry_calls = []
        self.threshold_payload = None

    def post_telemetry(self, coffee_lot_id, temperature, humidity, recorded_at):
        self.telemetry_calls.append(
            {
                "coffee_lot_id": coffee_lot_id,
                "temperature": temperature,
                "humidity": humidity,
                "recorded_at": recorded_at,
            }
        )
        return {"id": 100}

    def get_thresholds(self, coffee_lot_id):
        return self.threshold_payload


class RejectingBackendClient:
    def post_telemetry(self, coffee_lot_id, temperature, humidity, recorded_at):
        raise BackendRejectedError("coffee lot rejected")


class UnusedBackendClient:
    def post_telemetry(self, coffee_lot_id, temperature, humidity, recorded_at):
        raise AssertionError("backend should not be called for unassigned devices")


def register_local_reading(temperature=20, humidity=60):
    return IoTMonitoringApplicationService().register_reading(
        DEVICE_ID,
        temperature,
        humidity,
        datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc),
    )


def test_push_pending_readings_posts_mapped_readings_and_marks_them_synced(db_session):
    DeviceRepository.update_lot_id(DEVICE_ID, "42")
    register_local_reading()
    backend = SuccessfulBackendClient()
    service = TelemetrySyncService(backend_client=backend)

    result = service.push_pending_readings()

    assert result == {"pushed": 1, "skipped": 0, "examined": 1}
    assert SensorReadingRepository.count_unsynced() == 0
    assert backend.telemetry_calls == [
        {
            "coffee_lot_id": 42,
            "temperature": 20,
            "humidity": 60,
            "recorded_at": datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc),
        }
    ]


def test_push_pending_readings_keeps_unassigned_devices_pending(db_session):
    register_local_reading()
    service = TelemetrySyncService(backend_client=UnusedBackendClient())

    result = service.push_pending_readings()

    assert result == {"pushed": 0, "skipped": 1, "examined": 1}
    assert SensorReadingRepository.count_unsynced() == 1


def test_push_pending_readings_drops_backend_rejections_from_outbox(db_session):
    DeviceRepository.update_lot_id(DEVICE_ID, "42")
    register_local_reading()
    service = TelemetrySyncService(backend_client=RejectingBackendClient())

    result = service.push_pending_readings()

    assert result == {"pushed": 0, "skipped": 1, "examined": 1}
    assert SensorReadingRepository.count_unsynced() == 0


def test_pull_thresholds_applies_backend_values_and_sync_interval_floor(db_session):
    DeviceRepository.update_lot_id(DEVICE_ID, "42")
    backend = SuccessfulBackendClient()
    backend.threshold_payload = {
        "minTemperature": 15,
        "maxTemperature": 25,
        "minHumidity": 50,
        "maxHumidity": 70,
        "syncIntervalSeconds": 2,
    }
    service = TelemetrySyncService(backend_client=backend)

    thresholds = service.pull_thresholds(DEVICE_ID)
    current = StorageThresholdsRepository.find_current_by_device_id(DEVICE_ID)

    assert thresholds is not None
    assert current is not None
    assert current.min_temperature == 15
    assert current.max_temperature == 25
    assert current.min_humidity == 50
    assert current.max_humidity == 70
    assert service.last_interval_seconds == 5
