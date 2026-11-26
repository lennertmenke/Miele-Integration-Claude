"""Tests for the HA-independent API helpers."""

from custom_components.miele_plus.api import SSEParser
from custom_components.miele_plus.models import MieleDevice

from .conftest import WASHER


def test_sse_parser_handles_split_chunks() -> None:
    parser = SSEParser()
    payload = 'event: devices\ndata: {"a": 1}\n\nevent: ping\ndata: ping\n\n'
    events = []
    for i in range(0, len(payload), 3):
        events.extend(parser.feed(payload[i : i + 3]))
    assert events == [("devices", '{"a": 1}'), ("ping", "ping")]


def test_sse_parser_crlf_comments_and_long_lines() -> None:
    parser = SSEParser()
    big = "x" * 500_000
    events = parser.feed(f": comment\r\nevent: actions\r\ndata: {big}\r\n\r\n")
    assert events == [("actions", big)]


def test_device_model() -> None:
    dev = MieleDevice("1", WASHER)
    assert dev.status_key == "running"
    assert dev.remaining_minutes == 90
    assert dev.elapsed_minutes == 30
    assert dev.progress == 25
    assert dev.target_temperature(0) == 40
    assert dev.temperature(0) is None
    assert dev.energy_forecast == 30
    assert dev.spin_speed == 1400
    assert dev.name == "Waschmaschine"


# Real payload of a WSB683 (taken from a user's diagnostics, serial removed)
REAL_WSB683 = {
    "ident": {
        "type": {
            "key_localized": "Device type",
            "value_raw": 1,
            "value_localized": "Washing machine",
        },
        "deviceName": "",
        "protocolVersion": 4,
        "deviceIdentLabel": {"fabIndex": "60", "techType": "WSB683", "matNumber": "12397150"},
        "xkmIdentLabel": {"techType": "EK057", "releaseVersion": "08.37"},
    },
    "state": {
        "ProgramID": {"value_raw": 123, "value_localized": "Dark garments / Denim"},
        "status": {"value_raw": 5, "value_localized": "In use"},
        "programType": {"value_raw": 1, "value_localized": "Program"},
        "programPhase": {"value_raw": 260, "value_localized": "Main wash"},
        "remainingTime": [0, 39],
        "startTime": [0, 0],
        "targetTemperature": [
            {"value_raw": 3000, "value_localized": 30, "unit": "Celsius"},
            {"value_raw": -32768, "value_localized": None, "unit": "Celsius"},
        ],
        "coreTargetTemperature": [{"value_raw": -3276800, "value_localized": None}],
        "temperature": [{"value_raw": -32768, "value_localized": None}],
        "coreTemperature": [{"value_raw": -3276800, "value_localized": None}],
        "signalInfo": False,
        "signalFailure": False,
        "signalDoor": False,
        "remoteEnable": {"fullRemoteControl": True, "smartGrid": True, "mobileStart": True},
        "ambientLight": None,
        "light": None,
        "elapsedTime": [1, 10],
        "spinningSpeed": {"unit": "rpm", "value_raw": 1200, "value_localized": "1200"},
        "dryingStep": {"value_raw": None, "value_localized": ""},
        "ventilationStep": {"value_raw": None, "value_localized": ""},
        "plateStep": [],
        "ecoFeedback": {
            "currentWaterConsumption": {"unit": "l", "value": 20},
            "currentEnergyConsumption": {"unit": "kWh", "value": 0.4},
            "waterForecast": 0.3,
            "energyForecast": 0.4,
        },
        "batteryLevel": None,
    },
}


def test_real_payload() -> None:
    dev = MieleDevice("x", REAL_WSB683, actions={"processAction": [2], "powerOff": True})
    assert dev.model == "WSB683"
    assert dev.sw_version == "08.37"
    assert dev.status_key == "running"
    assert dev.program_name == "Dark garments / Denim"
    assert dev.remaining_minutes == 39
    assert dev.progress == 64
    assert dev.target_temperature(0) == 30
    assert dev.core_temperature is None
    assert dev.core_target_temperature is None
    assert dev.drying_step is None
    assert dev.ventilation_step is None
    assert dev.light_on is None
    assert dev.water_consumption == 20
    assert dev.energy_forecast == 40
    assert dev.process_actions() == [2]
    assert dev.can("powerOff") and not dev.can("powerOn")
