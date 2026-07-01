Feature: Local actuator control
  The edge evaluates each reading against the current thresholds and returns
  independent humidity/temperature alerts instantly, without depending on the
  backend. The firmware uses these alerts to drive one actuator per variable.

  Background:
    Given an authenticated device with default thresholds

  Scenario: Humidity above the maximum activates the humidity actuator
    When the device sends a reading with temperature 21 and humidity 80
    Then the response status is "DANGER"
    And the humidity alert is on
    And the temperature alert is off
    And an "ACTIVATE" actuator event is recorded

  Scenario: Temperature above the maximum does not activate the humidity actuator
    When the device sends a reading with temperature 30 and humidity 60
    Then the response status is "DANGER"
    And the humidity alert is off
    And the temperature alert is on
    And no actuator event is recorded

  Scenario: A reading within range keeps every actuator off
    When the device sends a reading with temperature 20 and humidity 60
    Then the response status is "OPTIMAL"
    And the humidity alert is off
    And the temperature alert is off
    And no actuator event is recorded
