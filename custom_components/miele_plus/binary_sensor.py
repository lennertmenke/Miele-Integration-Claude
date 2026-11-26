"""Binary sensor platform for Miele Plus."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACTIVE_STATES
from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MieleBinarySensorDescription(MieleEntityDescription, BinarySensorEntityDescription):
    """Describes a Miele binary sensor."""

    value_fn: Callable[[MieleDevice], bool | None]


BINARY_SENSORS: tuple[MieleBinarySensorDescription, ...] = (
    MieleBinarySensorDescription(
        key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.is_connected,
    ),
    MieleBinarySensorDescription(
        key="running",
        translation_key="running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: d.status_raw in ACTIVE_STATES,
    ),
    MieleBinarySensorDescription(
        key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda d: d.signal_door,
    ),
    MieleBinarySensorDescription(
        key="failure",
        translation_key="failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: d.signal_failure,
    ),
    MieleBinarySensorDescription(
        key="info",
        translation_key="info",
        value_fn=lambda d: d.signal_info,
    ),
    MieleBinarySensorDescription(
        key="remote_control",
        translation_key="remote_control",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.full_remote_control,
    ),
    MieleBinarySensorDescription(
        key="smart_grid",
        translation_key="smart_grid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.smart_grid,
    ),
    MieleBinarySensorDescription(
        key="mobile_start",
        translation_key="mobile_start",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.mobile_start,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        for desc in BINARY_SENSORS:
            if desc.exists_fn(dev):
                yield MieleBinarySensor(coordinator, dev.serial, desc)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleBinarySensor(MieleEntity, BinarySensorEntity):
    """Miele binary sensor."""

    entity_description: MieleBinarySensorDescription

    def __init__(self, coordinator, serial, description) -> None:  # type: ignore[no-untyped-def]
        """Initialize."""
        super().__init__(coordinator, serial, description)

    @property
    def is_on(self) -> bool | None:
        """Return the state (everything is off while the washer is offline)."""
        dev = self.device
        if not dev.is_connected and self.entity_description.key != "connected":
            return False
        return self.entity_description.value_fn(dev)
