"""The Miele Plus integration."""

from __future__ import annotations

import logging

from aiohttp import ClientResponseError
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow, config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .api import MieleApi, MieleAuthError
from .const import CONF_LANGUAGE, DEFAULT_LANGUAGE, DOMAIN
from .coordinator import MieleConfigEntry, MieleCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-wide services."""
    async_setup_services(hass)
    return True


def _resolve_language(hass: HomeAssistant, entry: MieleConfigEntry) -> str:
    language = entry.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
    if language == DEFAULT_LANGUAGE:
        language = (hass.config.language or "en").split("-")[0]
    return language


async def async_setup_entry(hass: HomeAssistant, entry: MieleConfigEntry) -> bool:
    """Set up Miele Plus from a config entry."""
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    async def token_getter(force_refresh: bool) -> str:
        try:
            if force_refresh:
                new_token = await implementation.async_refresh_token(oauth_session.token)
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "token": new_token}
                )
            else:
                await oauth_session.async_ensure_token_valid()
        except ClientResponseError as err:
            if 400 <= err.status < 500:
                raise MieleAuthError("Refresh token rejected") from err
            raise
        return oauth_session.token["access_token"]

    api = MieleApi(async_get_clientsession(hass), token_getter, _resolve_language(hass, entry))
    coordinator = MieleCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start_push()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: MieleConfigEntry) -> None:
    # Token refreshes also update the entry - only reload on option changes
    if dict(entry.options) != entry.runtime_data.options_snapshot:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MieleConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MieleConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow removing devices that are no longer part of the account."""
    serials = {ident[1] for ident in device_entry.identifiers if ident[0] == DOMAIN}
    return not serials & set(entry.runtime_data.data or {})
