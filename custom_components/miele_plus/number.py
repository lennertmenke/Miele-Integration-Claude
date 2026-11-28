"""Number platform for Miele Plus (oven target temperature while running)."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 1

DESCRIPTION = MieleEntityDescription(
    key="set_target_temperature", translation_key="set_target_temperature"
)
DEFAULT_LIMITS = (30.0, 250.0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        if dev.is_oven:
            yield MieleOvenTargetTemperature(coordinator, dev.serial, DESCRIPTION)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleOvenTargetTemperature(MieleEntity, NumberEntity):
    """Change the oven temperature of the running program."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 5
    _attr_mode = NumberMode.BOX
    _requires_connection = True

    @property
    def available(self) -> bool:
        """Only adjustable while the oven reports an allowed range."""
        return super().available and self.device.target_temperature_limits(0) is not None

    @property
    def native_min_value(self) -> float:
        """Minimum."""
        return (self.device.target_temperature_limits(0) or DEFAULT_LIMITS)[0]

    @property
    def native_max_value(self) -> float:
        """Maximum."""
        return (self.device.target_temperature_limits(0) or DEFAULT_LIMITS)[1]

    @property
    def native_value(self) -> float | None:
        """Current target temperature."""
        return self.device.target_temperature(0)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new target temperature."""
        await self.coordinator.async_send_action(
            self._serial, {"targetTemperature": [{"zone": 1, "value": int(round(value))}]}
        )
