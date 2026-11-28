"""Config subentry flow: create and edit oven recipes in the UI."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
import voluptuous as vol

from .const import (
    CONF_RECIPE_CORE_TEMPERATURE,
    CONF_RECIPE_DEVICE,
    CONF_RECIPE_DURATION,
    CONF_RECIPE_EXTRA,
    CONF_RECIPE_NAME,
    CONF_RECIPE_NOTES,
    CONF_RECIPE_PROGRAM,
    CONF_RECIPE_PROGRAM_NAME,
    CONF_RECIPE_TEMPERATURE,
)
from .coordinator import MieleCoordinator
from .models import MieleDevice


class RecipeSubentryFlow(ConfigSubentryFlow):
    """Add or edit a recipe (program + baking parameters) for an oven."""

    _device: str | None = None

    # ----------------------------------------------------------- helpers

    def _coordinator(self) -> MieleCoordinator | None:
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data

    def _ovens(self) -> dict[str, MieleDevice]:
        coordinator = self._coordinator()
        if coordinator is None:
            return {}
        return {s: d for s, d in (coordinator.data or {}).items() if d.is_oven}

    async def _program_options(self, serial: str) -> list[SelectOptionDict]:
        coordinator = self._coordinator()
        if coordinator is None:
            return []
        dev = (coordinator.data or {}).get(serial)
        if dev is None:
            return []
        programs = dev.programs or await coordinator.async_load_programs(serial)
        return [
            SelectOptionDict(
                value=str(p["programId"]), label=str(p.get("program") or p["programId"])
            )
            for p in programs
            if "programId" in p
        ]

    def _program_name(self, serial: str, program_id: int) -> str:
        coordinator = self._coordinator()
        dev = (coordinator.data or {}).get(serial) if coordinator else None
        info = dev.program_info(program_id) if dev else None
        return str((info or {}).get("program") or program_id)

    async def _schema(self, serial: str) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_RECIPE_NAME): TextSelector(),
                vol.Required(CONF_RECIPE_PROGRAM): SelectSelector(
                    SelectSelectorConfig(
                        options=await self._program_options(serial),
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_RECIPE_TEMPERATURE): NumberSelector(
                    NumberSelectorConfig(
                        min=30,
                        max=300,
                        step=5,
                        unit_of_measurement="°C",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_RECIPE_DURATION): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=720,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_RECIPE_CORE_TEMPERATURE): NumberSelector(
                    NumberSelectorConfig(
                        min=20,
                        max=100,
                        step=1,
                        unit_of_measurement="°C",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_RECIPE_EXTRA): ObjectSelector(),
                vol.Optional(CONF_RECIPE_NOTES): TextSelector(TextSelectorConfig(multiline=True)),
            }
        )

    def _validate(self, user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        errors: dict[str, str] = {}
        data = {k: v for k, v in user_input.items() if v not in (None, "", {})}
        try:
            data[CONF_RECIPE_PROGRAM] = int(str(user_input[CONF_RECIPE_PROGRAM]).strip())
        except (TypeError, ValueError):
            errors[CONF_RECIPE_PROGRAM] = "invalid_program"
            return data, errors
        extra = data.get(CONF_RECIPE_EXTRA)
        if extra is not None and not isinstance(extra, dict):
            errors[CONF_RECIPE_EXTRA] = "invalid_extra"
        for key in (CONF_RECIPE_TEMPERATURE, CONF_RECIPE_DURATION, CONF_RECIPE_CORE_TEMPERATURE):
            if key in data:
                data[key] = int(data[key])
        return data, errors

    # -------------------------------------------------------------- steps

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Choose the oven (skipped when there is only one)."""
        if self._coordinator() is None:
            return self.async_abort(reason="entry_not_loaded")
        ovens = self._ovens()
        if not ovens:
            return self.async_abort(reason="no_oven")
        if len(ovens) == 1:
            self._device = next(iter(ovens))
            return await self.async_step_recipe()
        if user_input is not None:
            self._device = user_input[CONF_RECIPE_DEVICE]
            return await self.async_step_recipe()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RECIPE_DEVICE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=serial, label=dev.name)
                                for serial, dev in ovens.items()
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name, program and baking parameters of a new recipe."""
        assert self._device is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input)
            if not errors:
                data[CONF_RECIPE_DEVICE] = self._device
                data[CONF_RECIPE_PROGRAM_NAME] = self._program_name(
                    self._device, data[CONF_RECIPE_PROGRAM]
                )
                return self.async_create_entry(title=data[CONF_RECIPE_NAME], data=data)
        schema = await self._schema(self._device)
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="recipe", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing recipe."""
        if self._coordinator() is None:
            return self.async_abort(reason="entry_not_loaded")
        subentry = self._get_reconfigure_subentry()
        serial = subentry.data[CONF_RECIPE_DEVICE]
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input)
            if not errors:
                data[CONF_RECIPE_DEVICE] = serial
                data[CONF_RECIPE_PROGRAM_NAME] = self._program_name(
                    serial, data[CONF_RECIPE_PROGRAM]
                )
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=data[CONF_RECIPE_NAME], data=data
                )
        suggested = dict(user_input or subentry.data)
        suggested[CONF_RECIPE_PROGRAM] = str(suggested.get(CONF_RECIPE_PROGRAM, ""))
        schema = self.add_suggested_values_to_schema(await self._schema(serial), suggested)
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
