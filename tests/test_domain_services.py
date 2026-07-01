from datetime import timezone

import pytest

from iotmonitoring.domain.entities import SensorReading, StorageThresholds
from iotmonitoring.domain.services import (
    ACTUATOR_ACTIVATE,
    ACTUATOR_NONE,
    STATUS_DANGER,
    STATUS_OPTIMAL,
    STATUS_WARNING,
    SensorReadingService,
    StorageConditionService,
    StorageThresholdService,
)


def test_create_reading_normalizes_numeric_values_and_timestamp():
    reading = SensorReadingService.create_reading(
        "tracksilo-001",
        "21.5",
        "63.2",
        "2026-06-30T10:30:00-05:00",
    )

    assert reading.device_id == "tracksilo-001"
    assert reading.temperature == 21.5
    assert reading.humidity == 63.2
    assert reading.recorded_at.tzinfo == timezone.utc
    assert reading.recorded_at.hour == 15


@pytest.mark.parametrize(
    ("temperature", "humidity", "message"),
    [
        (-40.1, 60, "temperature is outside the physical sensor range"),
        (80.1, 60, "temperature is outside the physical sensor range"),
        (20, -0.1, "humidity is outside the physical sensor range"),
        (20, 100.1, "humidity is outside the physical sensor range"),
    ],
)
def test_create_reading_rejects_values_outside_sensor_range(temperature, humidity, message):
    with pytest.raises(ValueError, match=message):
        SensorReadingService.create_reading("tracksilo-001", temperature, humidity)


@pytest.mark.parametrize(
    ("min_temperature", "max_temperature", "min_humidity", "max_humidity", "message"),
    [
        (25, 20, 50, 70, "min_temperature must be lower"),
        (18, 24, 80, 70, "min_humidity must be lower"),
        (-41, 24, 50, 70, "temperature thresholds must be between"),
        (18, 81, 50, 70, "temperature thresholds must be between"),
        (18, 24, -1, 70, "humidity thresholds must be between"),
        (18, 24, 50, 101, "humidity thresholds must be between"),
    ],
)
def test_threshold_synchronization_rejects_invalid_ranges(
    min_temperature,
    max_temperature,
    min_humidity,
    max_humidity,
    message,
):
    with pytest.raises(ValueError, match=message):
        StorageThresholdService.synchronize(
            "tracksilo-001",
            min_temperature,
            max_temperature,
            min_humidity,
            max_humidity,
        )


@pytest.mark.parametrize(
    (
        "reading",
        "expected_status",
        "expected_command",
        "expected_humidity_alert",
        "expected_temperature_alert",
    ),
    [
        (SensorReading("tracksilo-001", 20, 60, None), STATUS_OPTIMAL, ACTUATOR_NONE, False, False),
        (SensorReading("tracksilo-001", 17, 60, None), STATUS_WARNING, ACTUATOR_NONE, False, True),
        (SensorReading("tracksilo-001", 23, 60, None), STATUS_DANGER, ACTUATOR_NONE, False, True),
        (SensorReading("tracksilo-001", 20, 66, None), STATUS_DANGER, ACTUATOR_ACTIVATE, True, False),
        (SensorReading("tracksilo-001", 20, 54, None), STATUS_WARNING, ACTUATOR_NONE, True, False),
    ],
)
def test_storage_condition_evaluates_status_actuator_and_variable_alerts(
    reading,
    expected_status,
    expected_command,
    expected_humidity_alert,
    expected_temperature_alert,
):
    thresholds = StorageThresholds("tracksilo-001", 18, 22, 55, 65)

    humidity_alert, temperature_alert = StorageConditionService.environmental_alerts(
        reading,
        thresholds,
    )

    assert StorageConditionService.evaluate(reading, thresholds) == expected_status
    assert StorageConditionService.actuator_command(reading, thresholds) == expected_command
    assert humidity_alert is expected_humidity_alert
    assert temperature_alert is expected_temperature_alert
