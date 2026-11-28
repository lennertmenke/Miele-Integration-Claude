"""Light platform for Miele Plus (oven cavity light)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 1

DESCRIPTION = MieleEntityDescription(key="light", translation_key="light")
LIGHT_ON = 1
LIGHT_OFF = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the oven light."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        if dev.is_oven:
            yield MieleLight(coordinator, dev.serial, DESCRIPTION)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleLight(MieleEntity, LightEntity):
    """Oven cavity light."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def available(self) -> bool:
        """Switchable only while the oven offers the light action."""
        dev = self.device
        if not dev.is_connected:
            return super().available  # shows "off"
        return super().available and bool(dev.actions.get("light"))

    @property
    def is_on(self) -> bool:
        """Return whether the light is on."""
        return bool(self.device.is_connected and self.device.light_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        await self.coordinator.async_send_action(self._serial, {"light": LIGHT_ON})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self.coordinator.async_send_action(self._serial, {"light": LIGHT_OFF})
