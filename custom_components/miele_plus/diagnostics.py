"""Diagnostics for Miele Plus."""

from __future__ import annotations

import hashlib
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import MieleConfigEntry

TO_REDACT = {"access_token", "refresh_token", "id_token", "fabNumber", "deviceName"}


def _anon(serial: str) -> str:
    return "dev_" + hashlib.sha256(serial.encode()).hexdigest()[:10]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MieleConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    devices = {
        _anon(serial): {
            "raw": async_redact_data(dev.raw, TO_REDACT),
            "actions": dev.actions,
            "programs": dev.programs,
            "actions_age_s": round(dev.actions_age),
        }
        for serial, dev in (coordinator.data or {}).items()
    }
    return {
        "entry": {
            "options": dict(entry.options),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "connection": {
            "push_enabled": coordinator.use_push,
            "push_connected": coordinator.push_connected,
            "push_connected_since": str(coordinator.push_connected_since),
            "last_push_message": str(coordinator.last_push_message),
            "last_successful_update": str(coordinator.last_successful_update),
            "update_interval": str(coordinator.update_interval),
            "last_error": coordinator.last_error,
            "stats": coordinator.stats,
            "language": coordinator.api.language,
        },
        "devices": devices,
    }
