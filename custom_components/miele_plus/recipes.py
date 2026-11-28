"""Recipes: stored baking parameters that set up an oven with one click.

Recipes live as config subentries of the Miele Plus entry. Starting one:

1. switches the oven on if it is off (and remote power-on is allowed),
2. selects the program with temperature / duration / core temperature,
3. presses "start" if the oven only selected the program,
4. fires a ``recipe_started`` event.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_RECIPE_CORE_TEMPERATURE,
    CONF_RECIPE_DURATION,
    CONF_RECIPE_EXTRA,
    CONF_RECIPE_NAME,
    CONF_RECIPE_PROGRAM,
    CONF_RECIPE_TEMPERATURE,
    DOMAIN,
    EVENT_MIELE,
    EVENT_RECIPE_STARTED,
    SIGNAL_DEVICE_EVENT,
    MieleStatus,
    ProcessAction,
)
from .coordinator import MieleCoordinator
from .models import MieleDevice

_LOGGER = logging.getLogger(__name__)

POWER_ON_TIMEOUT = 30
START_CONFIRM_TIMEOUT = 15
# Names under which ovens may report the food-probe parameter of a program
CORE_PARAMETER_KEYS = ("mealTemperature", "coreTemperature", "coreTargetTemperature")


def _error(key: str, **placeholders: Any) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def _validation_error(key: str, **placeholders: Any) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def build_program_body(dev: MieleDevice, recipe: dict[str, Any]) -> dict[str, Any]:
    """Translate a stored recipe into the body of PUT /devices/{id}/programs."""
    program_id = int(recipe[CONF_RECIPE_PROGRAM])
    body: dict[str, Any] = {"programId": program_id}
    info = dev.program_info(program_id) or {}
    params: dict[str, Any] = info.get("parameters") or {}

    temperature = recipe.get(CONF_RECIPE_TEMPERATURE)
    if temperature is not None:
        _check_range(params.get("temperature"), temperature, "temperature")
        body["temperature"] = int(temperature)

    duration = recipe.get(CONF_RECIPE_DURATION)
    if duration:
        minutes = int(duration)
        body["duration"] = [minutes // 60, minutes % 60]

    core = recipe.get(CONF_RECIPE_CORE_TEMPERATURE)
    if core is not None:
        key = next((k for k in CORE_PARAMETER_KEYS if k in params), None)
        if key is None and params:
            # The oven told us which parameters this program accepts remotely
            raise _validation_error(
                "core_temperature_unsupported", program=info.get("program", program_id)
            )
        key = key or CORE_PARAMETER_KEYS[0]
        _check_range(params.get(key), core, "core_temperature")
        body[key] = int(core)

    extra = recipe.get(CONF_RECIPE_EXTRA)
    if isinstance(extra, dict):
        body.update(extra)
    return body


def _check_range(spec: Any, value: float, field: str) -> None:
    if not isinstance(spec, dict):
        return
    low, high = spec.get("min"), spec.get("max")
    too_low = isinstance(low, int | float) and value < low
    too_high = isinstance(high, int | float) and value > high
    if too_low or too_high:
        raise _validation_error("value_out_of_range", field=field, value=value, min=low, max=high)


async def _wait_for(
    coordinator: MieleCoordinator,
    serial: str,
    predicate: Callable[[MieleDevice], bool],
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dev = (coordinator.data or {}).get(serial)
        if dev is not None and predicate(dev):
            return True
        await asyncio.sleep(1)
        if not coordinator.push_connected:
            await coordinator.async_refresh()
    dev = (coordinator.data or {}).get(serial)
    return dev is not None and predicate(dev)


async def async_start_recipe(
    coordinator: MieleCoordinator, serial: str, recipe: dict[str, Any]
) -> None:
    """Set the oven to the stored recipe parameters and start it."""
    name = recipe.get(CONF_RECIPE_NAME, "?")
    dev = (coordinator.data or {}).get(serial)
    if dev is None or not dev.is_connected:
        raise _error("device_offline", device=dev.name if dev else serial)

    if not dev.is_on:
        if not dev.can("powerOn"):
            raise _error("power_on_not_allowed", device=dev.name)
        await coordinator.async_send_action(serial, {"powerOn": True})
        if not await _wait_for(coordinator, serial, lambda d: d.is_on, POWER_ON_TIMEOUT):
            raise _error("power_on_failed", device=dev.name)
        dev = coordinator.data[serial]

    if not dev.programs:
        await coordinator.async_load_programs(serial)
        dev = coordinator.data[serial]

    body = build_program_body(dev, recipe)
    _LOGGER.debug("Starting recipe %s on %s: %s", name, serial, body)
    await coordinator.async_start_program(serial, body)

    # Some ovens only select the program; press start in that case
    started = await _wait_for(
        coordinator,
        serial,
        lambda d: (
            d.status_raw
            in (MieleStatus.RUNNING, MieleStatus.WAITING_TO_START, MieleStatus.PROGRAMMED)
        ),
        START_CONFIRM_TIMEOUT,
    )
    dev = coordinator.data[serial]
    if (
        started
        and dev.status_raw == MieleStatus.PROGRAMMED
        and ProcessAction.START in dev.process_actions()
    ):
        await coordinator.async_send_action(serial, {"processAction": int(ProcessAction.START)})

    data = {
        "device_id": serial,
        "device_name": dev.name,
        "type": EVENT_RECIPE_STARTED,
        "recipe": name,
        "program_id": body["programId"],
        "temperature": body.get("temperature"),
        "duration": recipe.get(CONF_RECIPE_DURATION),
    }
    coordinator.hass.bus.async_fire(EVENT_MIELE, data)
    async_dispatcher_send(
        coordinator.hass, SIGNAL_DEVICE_EVENT.format(serial), EVENT_RECIPE_STARTED, data
    )
