"""Services for Miele Plus."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .const import (
    DOMAIN,
    SERVICE_GET_PROGRAMS,
    SERVICE_REFRESH,
    SERVICE_SEND_ACTION,
    SERVICE_SET_START_TIME,
    SERVICE_START_PROGRAM,
)
from .coordinator import MieleCoordinator

ATTR_DEVICE_ID = "device_id"

DEVICE_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})

START_PROGRAM_SCHEMA = DEVICE_SCHEMA.extend(
    {
        vol.Exclusive("program_id", "program"): vol.Coerce(int),
        vol.Exclusive("program", "program"): cv.string,
        vol.Optional("temperature"): vol.Coerce(int),
        vol.Optional("duration"): cv.positive_time_period,
        vol.Optional("start_delay"): cv.positive_time_period,
    }
)

SET_START_TIME_SCHEMA = DEVICE_SCHEMA.extend({vol.Required("delay"): cv.positive_time_period})

SEND_ACTION_SCHEMA = DEVICE_SCHEMA.extend(
    {vol.Required("action"): vol.Schema(dict, extra=vol.ALLOW_EXTRA)}
)

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_DEVICE_ID): cv.string})


def _hours_minutes(delta: timedelta) -> list[int]:
    minutes = int(delta.total_seconds() // 60)
    return [minutes // 60, minutes % 60]


@callback
def _resolve(hass: HomeAssistant, device_id: str) -> tuple[MieleCoordinator, str]:
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device",
            translation_placeholders={"device_id": device_id},
        )
    serial = next((ident[1] for ident in device.identifiers if ident[0] == DOMAIN), None)
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED and serial:
            return entry.runtime_data, serial
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_device",
        translation_placeholders={"device_id": device_id},
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register services."""

    async def start_program(call: ServiceCall) -> None:
        coordinator, serial = _resolve(hass, call.data[ATTR_DEVICE_ID])
        program_id = call.data.get("program_id")
        if program_id is None and (name := call.data.get("program")):
            programs = coordinator.data[serial].programs or await coordinator.async_load_programs(
                serial
            )
            match = next(
                (p for p in programs if str(p.get("program", "")).casefold() == name.casefold()),
                None,
            )
            if match is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_program",
                    translation_placeholders={"program": name},
                )
            program_id = match["programId"]
        if program_id is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="program_required"
            )
        body: dict[str, Any] = {"programId": program_id}
        if (temperature := call.data.get("temperature")) is not None:
            body["temperature"] = temperature
        if (duration := call.data.get("duration")) is not None:
            body["duration"] = _hours_minutes(duration)
        await coordinator.async_start_program(serial, body)
        if (delay := call.data.get("start_delay")) is not None:
            await coordinator.async_send_action(serial, {"startTime": _hours_minutes(delay)})

    async def set_start_time(call: ServiceCall) -> None:
        coordinator, serial = _resolve(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_send_action(
            serial, {"startTime": _hours_minutes(call.data["delay"])}
        )

    async def send_action(call: ServiceCall) -> None:
        coordinator, serial = _resolve(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_send_action(serial, dict(call.data["action"]))

    async def refresh(call: ServiceCall) -> None:
        if device_id := call.data.get(ATTR_DEVICE_ID):
            coordinators = [_resolve(hass, device_id)[0]]
        else:
            coordinators = [
                entry.runtime_data for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            ]
        for coordinator in coordinators:
            for dev in (coordinator.data or {}).values():
                dev.actions_updated = 0.0
            await coordinator.async_refresh()

    async def get_programs(call: ServiceCall) -> ServiceResponse:
        coordinator, serial = _resolve(hass, call.data[ATTR_DEVICE_ID])
        programs = await coordinator.async_load_programs(serial)
        return {"programs": programs}

    hass.services.async_register(
        DOMAIN, SERVICE_START_PROGRAM, start_program, schema=START_PROGRAM_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_START_TIME, set_start_time, schema=SET_START_TIME_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_ACTION, send_action, schema=SEND_ACTION_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PROGRAMS,
        get_programs,
        schema=DEVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
