"""Select platform for Miele Plus (program selection, hood fan level)."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import MieleConfigEntry
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 1

PROGRAM_DESCRIPTION = MieleEntityDescription(key="program_select", translation_key="program_select")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up select entities."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        yield MieleProgramSelect(coordinator, dev.serial, PROGRAM_DESCRIPTION)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


def program_label(program: dict) -> str:
    """Return a unique label for a program entry."""
    return str(program.get("program") or f"Program {program.get('programId')}")


class MieleProgramSelect(MieleEntity, SelectEntity):
    """Choose and start a program remotely."""

    _requires_connection = True

    @property
    def available(self) -> bool:
        """Available when the appliance offers remote programs."""
        return super().available and bool(self.device.programs)

    @property
    def options(self) -> list[str]:
        """Program names."""
        seen: list[str] = []
        for program in self.device.programs:
            label = program_label(program)
            if label not in seen:
                seen.append(label)
        return seen

    @property
    def current_option(self) -> str | None:
        """Currently running/selected program."""
        dev = self.device
        for program in dev.programs:
            if program.get("programId") == dev.program_id:
                return program_label(program)
        return None

    async def async_select_option(self, option: str) -> None:
        """Start the selected program."""
        for program in self.device.programs:
            if program_label(program) == option:
                await self.coordinator.async_start_program(
                    self._serial, {"programId": program["programId"]}
                )
                return
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_program",
            translation_placeholders={"program": option},
        )
