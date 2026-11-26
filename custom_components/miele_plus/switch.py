"""Switch platform for Miele Plus (power, superfreezing, supercooling)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    FREEZER_TYPES,
    FRIDGE_TYPES,
    PROGRAM_TYPES,
    DeviceType,
    MieleStatus,
    ProcessAction,
)
from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class MieleSwitchDescription(MieleEntityDescription, SwitchEntityDescription):
    """Describes a Miele switch."""

    is_on_fn: Callable[[MieleDevice], bool | None]
    on_body: dict[str, Any]
    off_body: dict[str, Any]
    on_allowed_fn: Callable[[MieleDevice], bool]
    off_allowed_fn: Callable[[MieleDevice], bool]


SWITCHES: tuple[MieleSwitchDescription, ...] = (
    MieleSwitchDescription(
        key="power",
        translation_key="power",
        is_on_fn=lambda d: d.is_on,
        on_body={"powerOn": True},
        off_body={"powerOff": True},
        on_allowed_fn=lambda d: d.can("powerOn"),
        off_allowed_fn=lambda d: d.can("powerOff"),
        exists_fn=lambda d: (
            "powerOn" in d.actions
            or "powerOff" in d.actions
            or d.type_raw in PROGRAM_TYPES | {DeviceType.HOOD}
        ),
    ),
    MieleSwitchDescription(
        key="superfreezing",
        translation_key="superfreezing",
        is_on_fn=lambda d: (
            d.status_raw in (MieleStatus.SUPERFREEZING, MieleStatus.SUPERCOOLING_SUPERFREEZING)
        ),
        on_body={"processAction": int(ProcessAction.START_SUPERFREEZING)},
        off_body={"processAction": int(ProcessAction.STOP_SUPERFREEZING)},
        on_allowed_fn=lambda d: ProcessAction.START_SUPERFREEZING in d.process_actions(),
        off_allowed_fn=lambda d: ProcessAction.STOP_SUPERFREEZING in d.process_actions(),
        exists_fn=lambda d: d.type_raw in FREEZER_TYPES,
    ),
    MieleSwitchDescription(
        key="supercooling",
        translation_key="supercooling",
        is_on_fn=lambda d: (
            d.status_raw in (MieleStatus.SUPERCOOLING, MieleStatus.SUPERCOOLING_SUPERFREEZING)
        ),
        on_body={"processAction": int(ProcessAction.START_SUPERCOOLING)},
        off_body={"processAction": int(ProcessAction.STOP_SUPERCOOLING)},
        on_allowed_fn=lambda d: ProcessAction.START_SUPERCOOLING in d.process_actions(),
        off_allowed_fn=lambda d: ProcessAction.STOP_SUPERCOOLING in d.process_actions(),
        exists_fn=lambda d: d.type_raw in FRIDGE_TYPES,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        for desc in SWITCHES:
            if desc.exists_fn(dev):
                yield MieleSwitch(coordinator, dev.serial, desc)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleSwitch(MieleEntity, SwitchEntity):
    """Miele switch with optimistic state until the cloud confirms."""

    entity_description: MieleSwitchDescription

    def __init__(self, *args: Any) -> None:
        """Initialize."""
        super().__init__(*args)
        self._optimistic: bool | None = None
        self._cancel_clear: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        """Available if the appliance currently accepts either direction."""
        if not super().available:
            return False
        dev = self.device
        desc = self.entity_description
        return desc.on_allowed_fn(dev) or desc.off_allowed_fn(dev)

    @property
    def is_on(self) -> bool | None:
        """Return state."""
        if self._optimistic is not None:
            return self._optimistic
        return self.entity_description.is_on_fn(self.device)

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._optimistic is not None and (
            self.entity_description.is_on_fn(self.device) == self._optimistic
        ):
            self._optimistic = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self.coordinator.async_send_action(self._serial, self.entity_description.on_body)
        self._set_optimistic(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self.coordinator.async_send_action(self._serial, self.entity_description.off_body)
        self._set_optimistic(False)

    @callback
    def _set_optimistic(self, value: bool) -> None:
        self._optimistic = value
        self.async_write_ha_state()
        if self._cancel_clear:
            self._cancel_clear()

        @callback
        def _clear(_now: Any) -> None:
            self._cancel_clear = None
            self._optimistic = None
            self.async_write_ha_state()

        # Fall back to the reported state if the cloud never confirms
        self._cancel_clear = async_call_later(self.hass, 60, _clear)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel pending timers."""
        if self._cancel_clear:
            self._cancel_clear()
        await super().async_will_remove_from_hass()
