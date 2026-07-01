"""Acceptance tests (pytest-bdd).

The Gherkin scenarios live in ``features/*.feature`` and describe the system from
the user's point of view. These step definitions glue that plain-English text to
the real edge, reusing the ``app_client`` fixture (full Flask + SQLite stack,
with the sync worker and the external backend neutralized).
"""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

DEVICE_ID = "tracksilo-001"
API_KEY = "test-api-key-123"

# Bind every scenario found under features/ to this module.
scenarios("features")


def auth_headers():
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


@pytest.fixture()
def context():
    """Mutable bag to carry state between steps of one scenario."""
    return {}


@given("an authenticated device with default thresholds")
def _authenticated_device(app_client, context):
    # The development device (tracksilo-001) is created by the db_session
    # fixture; its thresholds default to 18-22 C / 55-65 %RH on first read.
    context["headers"] = auth_headers()


@when(
    parsers.parse(
        "the device sends a reading with temperature {temperature:d} and humidity {humidity:d}"
    )
)
def _send_reading(app_client, context, temperature, humidity):
    response = app_client.post(
        "/api/v1/edge/readings",
        headers=context["headers"],
        json={"deviceId": DEVICE_ID, "temperature": temperature, "humidity": humidity},
    )
    assert response.status_code == 201
    context["reading"] = response.get_json()


@when("a manual sync is triggered")
def _trigger_sync(app_client, context):
    response = app_client.post(
        "/api/v1/edge/sync",
        headers=context["headers"],
        json={"deviceId": DEVICE_ID},
    )
    assert response.status_code == 200
    context["sync"] = response.get_json()


@then(parsers.parse('the response status is "{status}"'))
def _assert_status(context, status):
    assert context["reading"]["status"] == status


@then(parsers.parse("the humidity alert is {state}"))
def _assert_humidity_alert(context, state):
    assert context["reading"]["humidityAlert"] is (state == "on")


@then(parsers.parse("the temperature alert is {state}"))
def _assert_temperature_alert(context, state):
    assert context["reading"]["temperatureAlert"] is (state == "on")


@then(parsers.parse('an "{event_type}" actuator event is recorded'))
def _assert_actuator_event(app_client, context, event_type):
    events = app_client.get(
        f"/api/v1/edge/actuator-events?deviceId={DEVICE_ID}"
    ).get_json()["events"]
    assert len(events) == 1
    assert events[0]["eventType"] == event_type


@then("no actuator event is recorded")
def _assert_no_actuator_event(app_client):
    events = app_client.get(
        f"/api/v1/edge/actuator-events?deviceId={DEVICE_ID}"
    ).get_json()["events"]
    assert events == []


@then("no readings are pushed to the backend")
def _assert_none_pushed(context):
    assert context["sync"]["readingsPushed"] == 0


@then(parsers.parse("{count:d} reading remains pending"))
def _assert_pending(context, count):
    assert context["sync"]["readingsPending"] == count
