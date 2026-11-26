"""Light platform for Miele Plus (oven / hood / wine cabinet lights)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityDescription,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OVEN_TYPES, WINE_TYPES, DeviceType
from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class MieleLightDescription(MieleEntityDescription, LightEntityDescription):
    """Describes a Miele light."""

    action_key: str
    is_on_fn: Callable[[MieleDevice], bool | None]


LIGHTS: tuple[MieleLightDescription, ...] = (
    MieleLightDescription(
        key="light",
        translation_key="light",
        action_key="light",
        is_on_fn=lambda d: d.light_on,
        exists_fn=lambda d: (
            d.light_on is not None or d.type_raw in OVEN_TYPES | WINE_TYPES | {DeviceType.HOOD}
        ),
    ),
    MieleLightDescription(
        key="ambient_light",
        translation_key="ambient_light",
        action_key="ambientLight",
        is_on_fn=lambda d: d.ambient_light_on,
        exists_fn=lambda d: d.ambient_light_on is not None or d.type_raw == DeviceType.HOOD,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up lights."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        for desc in LIGHTS:
            if desc.exists_fn(dev):
                yield MieleLight(coordinator, dev.serial, desc)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleLight(MieleEntity, LightEntity):
    """Miele light."""

    entity_description: MieleLightDescription
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def available(self) -> bool:
        """Available while the appliance allows switching the light."""
        return super().available and bool(
            self.device.actions.get(self.entity_description.action_key)
        )

    @property
    def is_on(self) -> bool | None:
        """Return state."""
        return self.entity_description.is_on_fn(self.device)

    @property
    def _colors(self) -> list[str]:
        if self.entity_description.key != "ambient_light":
            return []
        return [str(c) for c in self.device.actions.get("colors") or []]

    @property
    def supported_features(self) -> LightEntityFeature:
        """Hoods support ambient light colors as effects."""
        return LightEntityFeature.EFFECT if self._colors else LightEntityFeature(0)

    @property
    def effect_list(self) -> list[str] | None:
        """Return the available colors."""
        return self._colors or None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        key = self.entity_description.action_key
        if (effect := kwargs.get(ATTR_EFFECT)) and effect in self._colors:
            await self.coordinator.async_send_action(self._serial, {"colors": effect})
            if self.is_on:
                return
        await self.coordinator.async_send_action(self._serial, {key: 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self.coordinator.async_send_action(
            self._serial, {self.entity_description.action_key: 2}
        )
