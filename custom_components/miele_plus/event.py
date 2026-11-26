"""Event platform for Miele Plus (program started/finished/... as event entities)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES, SIGNAL_DEVICE_EVENT
from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 0

DESCRIPTION = MieleEntityDescription(key="activity", translation_key="activity")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up event entities."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        yield MieleActivityEvent(coordinator, dev.serial, DESCRIPTION)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleActivityEvent(MieleEntity, EventEntity):
    """Fires on program and signal transitions."""

    _attr_event_types = EVENT_TYPES
    _always_available = True

    async def async_added_to_hass(self) -> None:
        """Subscribe to device events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DEVICE_EVENT.format(self._serial), self._on_event
            )
        )

    @callback
    def _on_event(self, event_type: str, data: dict[str, Any]) -> None:
        attributes = {k: v for k, v in data.items() if k not in ("type", "device_id")}
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
