"""Config flow for Miele Plus."""

from __future__ import annotations

import base64
from collections.abc import Mapping
import json
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .const import (
    CONF_LANGUAGE,
    CONF_POLL_INTERVAL,
    CONF_STALE_GRACE,
    CONF_USE_PUSH,
    DEFAULT_LANGUAGE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_STALE_GRACE,
    DEFAULT_USE_PUSH,
    DOMAIN,
)
from .coordinator import MieleConfigEntry

LANGUAGES = ["auto", "de", "en", "fr", "it", "nl", "es", "pl", "sv", "da", "nb", "fi", "cs"]


def _token_subject(token: dict[str, Any]) -> str | None:
    """Extract the user id from a JWT access token, if it is one."""
    access = token.get("access_token", "")
    parts = access.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return None
    return claims.get("sub") if isinstance(claims, dict) else None


class MieleFlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Handle the OAuth2 config flow."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Miele requires the 'vg' (country/language) parameter."""
        language = self.hass.config.language or "en"
        country = self.hass.config.country or "DE"
        return {"vg": f"{language.split('-')[0]}-{country}"}

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create or update the entry after successful authorization."""
        unique_id = _token_subject(data["token"]) or DOMAIN
        await self.async_set_unique_id(unique_id)
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            if DOMAIN not in (entry.unique_id, unique_id) and entry.unique_id != unique_id:
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Miele", data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauth."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: MieleConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return MieleOptionsFlow()


class MieleOptionsFlow(OptionsFlow):
    """Options: language, push, polling, stale grace period."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LANGUAGE, default=options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=LANGUAGES,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="language",
                    )
                ),
                vol.Required(
                    CONF_USE_PUSH, default=options.get(CONF_USE_PUSH, DEFAULT_USE_PUSH)
                ): bool,
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=20,
                        max=900,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_STALE_GRACE,
                    default=options.get(CONF_STALE_GRACE, DEFAULT_STALE_GRACE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=240,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
