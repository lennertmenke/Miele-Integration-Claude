"""Fixtures for Miele Plus tests."""

from __future__ import annotations

from collections.abc import Generator
import copy
import time
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.miele_plus.const import DOMAIN

SERIAL_WM = "000123456789"
SERIAL_FRIDGE = "000987654321"


def _temp(value: float | None) -> dict[str, Any]:
    raw = -32768 if value is None else int(value * 100)
    return {"value_raw": raw, "value_localized": value, "unit": "Celsius"}


WASHER = {
    "ident": {
        "type": {"value_raw": 1, "value_localized": "Waschmaschine"},
        "deviceName": "",
        "deviceIdentLabel": {"fabNumber": SERIAL_WM, "techType": "WCI870"},
        "xkmIdentLabel": {"techType": "EK057", "releaseVersion": "08.32"},
    },
    "state": {
        "ProgramID": {"value_raw": 1, "value_localized": "Baumwolle", "key_localized": "Programm"},
        "status": {"value_raw": 5, "value_localized": "In Betrieb"},
        "programType": {"value_raw": 1, "value_localized": "Eigenes Programm"},
        "programPhase": {"value_raw": 260, "value_localized": "Hauptwäsche"},
        "remainingTime": [1, 30],
        "startTime": [0, 0],
        "elapsedTime": [0, 30],
        "targetTemperature": [_temp(40), _temp(None), _temp(None)],
        "temperature": [_temp(None), _temp(None), _temp(None)],
        "signalInfo": False,
        "signalFailure": False,
        "signalDoor": False,
        "remoteEnable": {"fullRemoteControl": True, "smartGrid": False, "mobileStart": True},
        "light": None,
        "spinningSpeed": {"unit": "rpm", "value_raw": 1400, "value_localized": "1400"},
        "ecoFeedback": {
            "currentWaterConsumption": {"unit": "l", "value": 10},
            "currentEnergyConsumption": {"unit": "kWh", "value": 0.4},
            "waterForecast": 0.5,
            "energyForecast": 0.3,
        },
    },
}

FRIDGE = {
    "ident": {
        "type": {"value_raw": 21, "value_localized": "Kühl-Gefrier-Kombination"},
        "deviceName": "Küche",
        "deviceIdentLabel": {"fabNumber": SERIAL_FRIDGE, "techType": "KFN 7774"},
        "xkmIdentLabel": {"techType": "EK037", "releaseVersion": "03.10"},
    },
    "state": {
        "ProgramID": {"value_raw": 0, "value_localized": ""},
        "status": {"value_raw": 2, "value_localized": "Ein"},
        "targetTemperature": [_temp(4), _temp(-18), _temp(None)],
        "temperature": [_temp(4.5), _temp(-18.2), _temp(None)],
        "signalInfo": False,
        "signalFailure": False,
        "signalDoor": False,
        "remoteEnable": {"fullRemoteControl": True, "smartGrid": False, "mobileStart": False},
        "light": None,
    },
}

WASHER_ACTIONS = {
    "processAction": [2, 3],
    "light": [],
    "startTime": [],
    "powerOn": False,
    "powerOff": True,
    "targetTemperature": [],
}
FRIDGE_ACTIONS = {
    "processAction": [4, 6],
    "light": [],
    "powerOn": False,
    "powerOff": False,
    "targetTemperature": [{"zone": 1, "min": 1, "max": 9}, {"zone": 2, "min": -26, "max": -16}],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


@pytest.fixture
def devices() -> dict[str, Any]:
    """Raw device payload."""
    return {SERIAL_WM: copy.deepcopy(WASHER), SERIAL_FRIDGE: copy.deepcopy(FRIDGE)}


@pytest.fixture
def mock_api(devices: dict[str, Any]) -> Generator[dict[str, AsyncMock]]:
    """Patch the Miele API client."""
    actions = {SERIAL_WM: WASHER_ACTIONS, SERIAL_FRIDGE: FRIDGE_ACTIONS}
    base = "custom_components.miele_plus.api.MieleApi"
    with (
        patch(
            f"{base}.get_devices", AsyncMock(side_effect=lambda: copy.deepcopy(devices))
        ) as get_devices,
        patch(
            f"{base}.get_actions", AsyncMock(side_effect=lambda s: copy.deepcopy(actions[s]))
        ) as get_actions,
        patch(
            f"{base}.get_programs",
            AsyncMock(
                return_value=[
                    {"programId": 1, "program": "Baumwolle"},
                    {"programId": 3, "program": "Pflegeleicht"},
                ]
            ),
        ) as get_programs,
        patch(f"{base}.send_action", AsyncMock(return_value=None)) as send_action,
        patch(f"{base}.start_program", AsyncMock(return_value=None)) as start_program,
    ):
        yield {
            "get_devices": get_devices,
            "get_actions": get_actions,
            "get_programs": get_programs,
            "send_action": send_action,
            "start_program": start_program,
        }


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Config entry with a valid token and push disabled."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Miele",
        unique_id="user-1",
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": time.time() + 3600,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        },
        options={"use_push": False, "language": "de"},
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> MockConfigEntry:
    """Set up the integration."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential("client-id", "client-secret"), DOMAIN
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
