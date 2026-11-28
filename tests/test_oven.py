"""Tests for oven support and recipes (Miele DGC 7450)."""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.miele_plus import recipes
from custom_components.miele_plus.const import EVENT_MIELE
from custom_components.miele_plus.models import MieleDevice

from .conftest import OVEN, OVEN_PROGRAMS, SERIAL_OVEN, SERIAL_WM, _temp


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} missing; have {sorted(hass.states.async_entity_ids())}"
    return state.state


@pytest.fixture(autouse=True)
def fast_recipes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Don't wait for state confirmations in tests."""
    monkeypatch.setattr(recipes, "START_CONFIRM_TIMEOUT", 0)
    monkeypatch.setattr(recipes, "POWER_ON_TIMEOUT", 0)


async def test_oven_entities(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert _state(hass, "sensor.backofen_temperature") == "22.0"
    assert _state(hass, "light.backofen_light") == "off"
    assert hass.states.get("number.backofen_set_target_temperature") is not None
    assert hass.states.get("sensor.backofen_core_temperature") is not None
    # Washer-only entities are not created for the oven and vice versa
    assert hass.states.get("sensor.backofen_spin_speed") is None
    assert hass.states.get("sensor.backofen_water_total") is None
    assert hass.states.get("light.waschmaschine_light") is None


async def test_program_and_phase_show_off(
    hass: HomeAssistant, setup_integration: MockConfigEntry, devices: dict[str, Any]
) -> None:
    coordinator = setup_integration.runtime_data
    update = copy.deepcopy(devices[SERIAL_WM])
    update["state"]["status"] = {"value_raw": 1, "value_localized": "Aus"}
    coordinator._handle_push_event("devices", {SERIAL_WM: update})
    await hass.async_block_till_done()
    # The test entry uses language "de"
    assert _state(hass, "sensor.waschmaschine_program") == "Aus"
    assert _state(hass, "sensor.waschmaschine_program_phase") == "Aus"


async def test_temperature_reached_event(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    coordinator = setup_integration.runtime_data
    events = async_capture_events(hass, EVENT_MIELE)
    oven = copy.deepcopy(OVEN)
    oven["state"]["status"] = {"value_raw": 5, "value_localized": "In Betrieb"}
    oven["state"]["ProgramID"] = {"value_raw": 13, "value_localized": "Heißluft plus"}
    oven["state"]["targetTemperature"] = [_temp(180), _temp(None), _temp(None)]
    for temp in (120, 175, 181, 184, 178, 182):
        oven = copy.deepcopy(oven)
        oven["state"]["temperature"] = [_temp(temp), _temp(None), _temp(None)]
        coordinator._handle_push_event("devices", {SERIAL_OVEN: oven})
        await hass.async_block_till_done()
    reached = [e.data for e in events if e.data["type"] == "temperature_reached"]
    # Fired exactly once even though the oven cycles around the target
    assert len(reached) == 1
    assert reached[0]["target"] == 180
    assert _state(hass, "event.backofen_activity") != "unknown"


async def test_recipe_flow_and_start(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "recipe"), context={"source": SOURCE_USER}
    )
    # Only one oven -> straight to the recipe form with the oven's programs
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "recipe"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Pizza", "program_id": "abc"}
    )
    assert result["errors"] == {"program_id": "invalid_program"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Pizza", "program_id": "13", "temperature": 220, "duration": 12},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    subentry = next(iter(entry.subentries.values()))
    assert subentry.title == "Pizza"
    assert subentry.data["program_id"] == 13
    assert subentry.data["program_name"] == "Heißluft plus"

    # The entry reloads and offers a button on the oven
    state = hass.states.get("button.backofen_recipe_pizza")
    assert state is not None, sorted(hass.states.async_entity_ids("button"))
    assert state.attributes["temperature"] == 220

    events = async_capture_events(hass, EVENT_MIELE)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.backofen_recipe_pizza"}, blocking=True
    )
    mock_api["start_program"].assert_awaited_with(
        SERIAL_OVEN, {"programId": 13, "temperature": 220, "duration": [0, 12]}
    )
    assert any(e.data["type"] == "recipe_started" and e.data["recipe"] == "Pizza" for e in events)

    # Edit the recipe
    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Pizza", "program_id": "13", "temperature": 250, "duration": 10},
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert hass.states.get("button.backofen_recipe_pizza").attributes["temperature"] == 250


def test_build_program_body_validates() -> None:
    dev = MieleDevice(SERIAL_OVEN, OVEN, programs=copy.deepcopy(OVEN_PROGRAMS))
    body = recipes.build_program_body(
        dev, {"program_id": 19, "temperature": 100, "extra_parameters": {"steam": 1}}
    )
    assert body == {"programId": 19, "temperature": 100, "steam": 1}
    with pytest.raises(ServiceValidationError):
        recipes.build_program_body(dev, {"program_id": 19, "temperature": 180})
    with pytest.raises(ServiceValidationError):
        # Program 13 does not list a food-probe parameter
        recipes.build_program_body(dev, {"program_id": 13, "core_temperature": 65})
