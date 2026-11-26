"""Base entity and helpers for Miele Plus."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import MieleConfigEntry, MieleCoordinator
from .models import MieleDevice


@dataclass(frozen=True, kw_only=True)
class MieleEntityDescription(EntityDescription):
    """Common description fields."""

    exists_fn: Callable[[MieleDevice], bool] = lambda _: True
    available_fn: Callable[[MieleDevice], bool] = lambda _: True


class MieleEntity(CoordinatorEntity[MieleCoordinator]):
    """Base class for all Miele entities."""

    _attr_has_entity_name = True
    entity_description: MieleEntityDescription

    def __init__(
        self,
        coordinator: MieleCoordinator,
        serial: str,
        description: MieleEntityDescription,
        suffix: str | None = None,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._serial = serial
        key = description.key if suffix is None else f"{description.key}_{suffix}"
        self._attr_unique_id = f"{serial}_{key}"
        dev = self.device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer=MANUFACTURER,
            name=dev.name,
            model=dev.type_name,
            model_id=dev.model,
            serial_number=serial,
            sw_version=dev.sw_version,
            hw_version=dev.hw_version,
        )

    @property
    def device(self) -> MieleDevice:
        """Return the current device object."""
        return self.coordinator.data[self._serial]

    @property
    def available(self) -> bool:
        """Entity is available while the device is known and reachable."""
        if not super().available or self._serial not in (self.coordinator.data or {}):
            return False
        dev = self.device
        # Connectivity entities stay available to report "disconnected"
        if not dev.is_connected and not getattr(self, "_always_available", False):
            return False
        return self.entity_description.available_fn(dev)


@callback
def async_setup_device_entities(
    coordinator: MieleCoordinator,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[MieleDevice], Iterable[MieleEntity]],
) -> None:
    """Create entities for all devices, including devices added later."""
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new_entities: list[MieleEntity] = []
        for serial, dev in (coordinator.data or {}).items():
            if serial in known:
                continue
            known.add(serial)
            new_entities.extend(factory(dev))
        if new_entities:
            async_add_entities(new_entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
