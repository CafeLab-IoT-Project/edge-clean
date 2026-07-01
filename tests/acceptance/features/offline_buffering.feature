Feature: Offline telemetry buffering
  A reading is always stored locally (outbox pattern) and is never lost when the
  device is not yet mapped to a coffee lot or the backend is unavailable. It
  stays pending until it can be reconciled with the backend.

  Background:
    Given an authenticated device with default thresholds

  Scenario: A reading from an unassigned device stays pending after a sync
    When the device sends a reading with temperature 20 and humidity 60
    And a manual sync is triggered
    Then no readings are pushed to the backend
    And 1 reading remains pending
