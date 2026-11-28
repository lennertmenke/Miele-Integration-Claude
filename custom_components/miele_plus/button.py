"""Button platform for Miele Plus (start / stop / pause and recipes)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_RECIPE_DEVICE, DOMAIN, SUBENTRY_RECIPE, ProcessAction
from .coordinator import MieleConfigEntry, MieleCoordinator
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice
from .recipes import async_start_recipe

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

    # One button per stored recipe, attached to its oven
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_RECIPE:
            continue
        async_add_entities(
            [MieleRecipeButton(coordinator, entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class MieleButton(MieleEntity, ButtonEntity):
    """Send a process action."""

    entity_description: MieleButtonDescription
    _requires_connection = True

    @property
    def available(self) -> bool:
        """Only available while the appliance accepts the action."""
        return super().available and self.entity_description.action in self.device.process_actions()

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.async_send_action(
            self._serial, {"processAction": int(self.entity_description.action)}
        )


class MieleRecipeButton(CoordinatorEntity[MieleCoordinator], ButtonEntity):
    """Sets the oven to a stored recipe and starts it."""

    _attr_has_entity_name = True
    _attr_translation_key = "recipe"

    def __init__(
        self, coordinator: MieleCoordinator, entry: MieleConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._recipe: dict[str, Any] = dict(subentry.data)
        self._serial: str = subentry.data[CONF_RECIPE_DEVICE]
        self._attr_unique_id = f"{entry.entry_id}_recipe_{subentry.subentry_id}"
        self._attr_translation_placeholders = {"recipe": subentry.title}
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def available(self) -> bool:
        """Available while the oven is reachable (it is switched on if needed)."""
        dev = (self.coordinator.data or {}).get(self._serial)
        return super().available and dev is not None and dev.is_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Show the stored parameters."""
        return {k: v for k, v in self._recipe.items() if k != CONF_RECIPE_DEVICE}

    async def async_press(self) -> None:
        """Start the recipe."""
        await async_start_recipe(self.coordinator, self._serial, self._recipe)
