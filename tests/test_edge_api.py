DEVICE_ID = "tracksilo-001"
API_KEY = "test-api-key-123"


def auth_headers():
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def test_health_check(app_client):
    response = app_client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "edge-clean"}


def test_register_reading_requires_device_credentials(app_client):
    response = app_client.post(
        "/api/v1/edge/readings",
        json={"deviceId": DEVICE_ID, "temperature": 20, "humidity": 60},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Missing device_id or X-API-Key"


def test_register_reading_returns_humidity_danger_and_actuator_event(app_client):
    response = app_client.post(
        "/api/v1/edge/readings",
        headers=auth_headers(),
        json={"deviceId": DEVICE_ID, "temperature": 21, "humidity": 80},
    )

    body = response.get_json()
    assert response.status_code == 201
    assert body["status"] == "DANGER"
    assert body["actuatorCommand"] == "ACTIVATE"
    assert body["humidityAlert"] is True
    assert body["temperatureAlert"] is False

    latest = app_client.get(f"/api/v1/edge/readings/latest?deviceId={DEVICE_ID}")
    assert latest.status_code == 200
    assert latest.get_json()["readingId"] == body["readingId"]

    events = app_client.get(f"/api/v1/edge/actuator-events?deviceId={DEVICE_ID}")
    event_body = events.get_json()
    assert events.status_code == 200
    assert len(event_body["events"]) == 1
    assert event_body["events"][0]["eventType"] == "ACTIVATE"


def test_temperature_alert_does_not_activate_humidity_actuator(app_client):
    response = app_client.post(
        "/api/v1/edge/readings",
        headers=auth_headers(),
        json={"deviceId": DEVICE_ID, "temperature": 30, "humidity": 60},
    )

    body = response.get_json()
    assert response.status_code == 201
    assert body["status"] == "DANGER"
    assert body["actuatorCommand"] == "NONE"
    assert body["humidityAlert"] is False
    assert body["temperatureAlert"] is True

    events = app_client.get(f"/api/v1/edge/actuator-events?deviceId={DEVICE_ID}")
    assert events.status_code == 200
    assert events.get_json()["events"] == []


def test_update_thresholds_rejects_invalid_temperature_range(app_client):
    response = app_client.put(
        "/api/v1/edge/thresholds",
        headers=auth_headers(),
        json={
            "deviceId": DEVICE_ID,
            "minTemperature": 25,
            "maxTemperature": 20,
            "minHumidity": 55,
            "maxHumidity": 65,
        },
    )

    assert response.status_code == 400
    assert "min_temperature must be lower" in response.get_json()["error"]


def test_recent_readings_rejects_invalid_limit(app_client):
    response = app_client.get(f"/api/v1/edge/readings?deviceId={DEVICE_ID}&limit=0")

    assert response.status_code == 400
    assert response.get_json()["error"] == "limit must be between 1 and 100"


def test_sensor_status_marks_stale_reading_as_offline(app_client):
    app_client.post(
        "/api/v1/edge/readings",
        headers=auth_headers(),
        json={
            "deviceId": DEVICE_ID,
            "temperature": 20,
            "humidity": 60,
            "recordedAt": "2026-01-01T00:00:00Z",
        },
    )

    response = app_client.get(f"/api/v1/edge/sensor-status?deviceId={DEVICE_ID}")

    assert response.status_code == 200
    assert response.get_json()["connectionStatus"] == "OFFLINE"


def test_thresholds_endpoint_returns_defaults_for_new_device(app_client):
    response = app_client.get(f"/api/v1/edge/thresholds?deviceId={DEVICE_ID}")

    assert response.status_code == 200
    assert response.get_json() == {
        "deviceId": DEVICE_ID,
        "minTemperature": 18.0,
        "maxTemperature": 22.0,
        "minHumidity": 55.0,
        "maxHumidity": 65.0,
    }


def test_sync_requires_device_credentials(app_client):
    response = app_client.post("/api/v1/edge/sync", json={"deviceId": DEVICE_ID})

    assert response.status_code == 401


def test_sync_skips_unassigned_device_and_reports_pending(app_client):
    # Una lectura queda en el outbox (is_synced=false).
    app_client.post(
        "/api/v1/edge/readings",
        headers=auth_headers(),
        json={"deviceId": DEVICE_ID, "temperature": 20, "humidity": 60},
    )

    # El dispositivo de desarrollo no tiene lote: el sync no llama al backend,
    # la lectura se salta y sigue pendiente.
    response = app_client.post(
        "/api/v1/edge/sync",
        headers=auth_headers(),
        json={"deviceId": DEVICE_ID},
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["readingsPushed"] == 0
    assert body["readingsSkipped"] == 1
    assert body["thresholdsUpdated"] == 0
    assert body["readingsPending"] == 1


def test_device_announce_is_idempotent(app_client):
    first = app_client.post(
        "/api/v1/iam/devices/announce",
        json={"deviceId": "esp32-test-001"},
    )
    second = app_client.post(
        "/api/v1/iam/devices/announce",
        json={"deviceId": "esp32-test-001"},
    )

    first_body = first.get_json()
    second_body = second.get_json()
    assert first.status_code == 200
    assert second.status_code == 200
    assert first_body["api_key"] == second_body["api_key"]
    assert first_body["assigned"] is False
    assert second_body["assigned"] is False
