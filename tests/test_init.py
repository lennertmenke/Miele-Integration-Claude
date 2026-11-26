"""Integration tests for Miele Plus."""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.miele_plus.api import MieleConnectionError
from custom_components.miele_plus.const import DOMAIN, EVENT_MIELE

from .conftest import SERIAL_FRIDGE, SERIAL_WM


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} missing; have {sorted(hass.states.async_entity_ids())}"
    return state.state


async def test_setup_creates_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    assert setup_integration.state is ConfigEntryState.LOADED
    assert _state(hass, "sensor.waschmaschine_status") == "running"
    assert _state(hass, "sensor.waschmaschine_remaining_time") == "90"
    assert _state(hass, "sensor.waschmaschine_progress") == "25"
    assert _state(hass, "sensor.waschmaschine_program") == "Baumwolle"
    assert _state(hass, "binary_sensor.waschmaschine_running") == "on"
    # Only washing machines are supported: the fridge-freezer is ignored
    assert not [e for e in hass.states.async_entity_ids() if "kuche" in e]
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERIAL_FRIDGE)}) is None
    # start not allowed while running, stop/pause allowed
    assert _state(hass, "button.waschmaschine_start") == STATE_UNAVAILABLE
    assert _state(hass, "button.waschmaschine_stop") == "unknown"
    assert _state(hass, "switch.waschmaschine_power") == "on"
    assert _state(hass, "sensor.waschmaschine_finish_time") != "unknown"
    assert _state(hass, "sensor.waschmaschine_update_mode") == "polling"
    assert _state(hass, "sensor.waschmaschine_twindos_1_level") == "68"
    assert _state(hass, "sensor.waschmaschine_twindos_2_level") == "61"
    assert hass.states.get("sensor.waschmaschine_salt_level") is None


async def test_push_event_transitions_and_totals(
    hass: HomeAssistant, setup_integration: MockConfigEntry, devices: dict[str, Any]
) -> None:
    coordinator = setup_integration.runtime_data
    events = async_capture_events(hass, EVENT_MIELE)
    assert _state(hass, "sensor.waschmaschine_energy_total") == "0.0"

    update = copy.deepcopy(devices[SERIAL_WM])
    update["state"]["ecoFeedback"]["currentEnergyConsumption"]["value"] = 0.9
    coordinator._handle_push_event("devices", {SERIAL_WM: update})
    await hass.async_block_till_done()
    assert _state(hass, "sensor.waschmaschine_energy_total") == "0.5"

    update = copy.deepcopy(update)
    update["state"]["status"] = {"value_raw": 7, "value_localized": "Ende"}
    update["state"]["remainingTime"] = [0, 0]
    coordinator._handle_push_event("devices", {SERIAL_WM: update})
    await hass.async_block_till_done()
    assert [e.data["type"] for e in events] == ["program_finished"]
    assert events[0].data["energy_kwh"] == 0.9
    assert events[0].data["program"] == "Baumwolle"
    assert _state(hass, "sensor.waschmaschine_status") == "program_ended"
    assert _state(hass, "sensor.waschmaschine_progress") == "100"
    event_state = hass.states.get("event.waschmaschine_activity")
    assert event_state.attributes["event_type"] == "program_finished"

    # New program starts: counter resets to a low value -> added on top
    update = copy.deepcopy(update)
    update["state"]["status"] = {"value_raw": 5, "value_localized": "In Betrieb"}
    update["state"]["ecoFeedback"]["currentEnergyConsumption"]["value"] = 0.1
    coordinator._handle_push_event("devices", {SERIAL_WM: update})
    await hass.async_block_till_done()
    assert events[-1].data["type"] == "program_started"
    assert _state(hass, "sensor.waschmaschine_energy_total") == "0.6"


async def test_cloud_outage_keeps_state(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    coordinator = setup_integration.runtime_data
    mock_api["get_devices"].side_effect = MieleConnectionError("boom")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert _state(hass, "sensor.waschmaschine_status") == "running"
    assert coordinator.stats["stale_updates_served"] == 1

    coordinator._stale_grace = 0
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, "sensor.waschmaschine_status") == STATE_UNAVAILABLE


async def test_commands_and_services(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.waschmaschine_pause"}, blocking=True
    )
    mock_api["send_action"].assert_awaited_with(SERIAL_WM, {"processAction": 3})

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERIAL_WM)})
    await hass.services.async_call(
        DOMAIN,
        "start_program",
        {"device_id": device.id, "program": "pflegeleicht", "start_delay": {"hours": 2}},
        blocking=True,
    )
    mock_api["start_program"].assert_awaited_with(SERIAL_WM, {"programId": 3})
    mock_api["send_action"].assert_awaited_with(SERIAL_WM, {"startTime": [2, 0]})

    response = await hass.services.async_call(
        DOMAIN, "get_programs", {"device_id": device.id}, blocking=True, return_response=True
    )
    assert len(response["programs"]) == 2

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.waschmaschine_start_program", "option": "Baumwolle"},
        blocking=True,
    )
    mock_api["start_program"].assert_awaited_with(SERIAL_WM, {"programId": 1})


async def test_unload(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_elapsed_kept_and_auto_power_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    devices: dict[str, Any],
    mock_api: dict[str, AsyncMock],
) -> None:
    import asyncio

    coordinator = setup_integration.runtime_data
    coordinator.power_off_on_finish = True
    coordinator.power_off_delay = 0
    assert _state(hass, "sensor.waschmaschine_elapsed_time") == "30"

    update = copy.deepcopy(devices[SERIAL_WM])
    update["state"]["status"] = {"value_raw": 7, "value_localized": "Ende"}
    update["state"]["remainingTime"] = [0, 0]
    update["state"]["elapsedTime"] = [0, 0]
    coordinator._handle_push_event("devices", {SERIAL_WM: update})
    await hass.async_block_till_done()
    # Miele resets elapsedTime at the end; we keep the final value
    assert _state(hass, "sensor.waschmaschine_elapsed_time") == "30"

    await asyncio.sleep(1.2)
    await hass.async_block_till_done()
    mock_api["send_action"].assert_awaited_with(SERIAL_WM, {"powerOff": True})

    update = copy.deepcopy(update)
    update["state"]["status"] = {"value_raw": 1, "value_localized": "Aus"}
    coordinator._handle_push_event("devices", {SERIAL_WM: update})
    await hass.async_block_till_done()
    assert _state(hass, "sensor.waschmaschine_elapsed_time") == "0"
