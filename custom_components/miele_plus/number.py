"""Number platform for Miele Plus (fridge / freezer / wine target temperature)."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import COOLING_TYPES, FREEZER_TYPES, FRIDGE_TYPES, WINE_TYPES
from .coordinator import MieleConfigEntry, MieleCoordinator
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 1

DESCRIPTION = MieleEntityDescription(key="target_temperature")


def _default_limits(dev: MieleDevice, zone: int) -> tuple[float, float]:
    if dev.type_raw in WINE_TYPES:
        return 5.0, 20.0
    if dev.type_raw in FRIDGE_TYPES and zone == 0:
        return 1.0, 9.0
    if dev.type_raw in FREEZER_TYPES:
        return -28.0, -14.0
    return -28.0, 20.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        if dev.type_raw not in COOLING_TYPES:
            return
        zones = set(dev.target_temperature_zones()) | {0}
        for zone in sorted(zones):
            yield MieleTargetTemperature(coordinator, dev.serial, zone)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleTargetTemperature(MieleEntity, NumberEntity):
    """Target temperature of a cooling zone."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: MieleCoordinator, serial: str, zone: int) -> None:
        """Initialize."""
        super().__init__(coordinator, serial, DESCRIPTION, None if zone == 0 else str(zone + 1))
        self._zone = zone
        if zone == 0:
            self._attr_translation_key = "target_temperature"
        else:
            self._attr_translation_key = "target_temperature_zone"
            self._attr_translation_placeholders = {"zone": str(zone + 1)}

    @property
    def _limits(self) -> tuple[float, float]:
        dev = self.device
        return dev.target_temperature_limits(self._zone) or _default_limits(dev, self._zone)

    @property
    def native_min_value(self) -> float:
        """Minimum."""
        return self._limits[0]

    @property
    def native_max_value(self) -> float:
        """Maximum."""
        return self._limits[1]

    @property
    def available(self) -> bool:
        """Available while the appliance reports adjustable limits."""
        return super().available and self.device.target_temperature_limits(self._zone) is not None

    @property
    def native_value(self) -> float | None:
        """Return the target temperature."""
        return self.device.target_temperature(self._zone)

    async def async_set_native_value(self, value: float) -> None:
        """Set the target temperature."""
        await self.coordinator.async_send_action(
            self._serial,
            {"targetTemperature": [{"zone": self._zone + 1, "value": int(round(value))}]},
        )
