"""Button platform for Miele Plus (start / stop / pause)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ProcessAction
from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class MieleButtonDescription(MieleEntityDescription, ButtonEntityDescription):
    """Describes a Miele button."""

    action: ProcessAction


BUTTONS: tuple[MieleButtonDescription, ...] = (
    MieleButtonDescription(
        key="start",
        translation_key="start",
        action=ProcessAction.START,
    ),
    MieleButtonDescription(
        key="stop",
        translation_key="stop",
        action=ProcessAction.STOP,
    ),
    MieleButtonDescription(
        key="pause",
        translation_key="pause",
        action=ProcessAction.PAUSE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        for desc in BUTTONS:
            if desc.exists_fn(dev):
                yield MieleButton(coordinator, dev.serial, desc)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleButton(MieleEntity, ButtonEntity):
    """Send a process action."""

    entity_description: MieleButtonDescription

    @property
    def available(self) -> bool:
        """Only available while the appliance accepts the action."""
        return super().available and self.entity_description.action in self.device.process_actions()

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.async_send_action(
            self._serial, {"processAction": int(self.entity_description.action)}
        )
