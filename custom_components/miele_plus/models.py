"""Typed, defensive view on the raw Miele device JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from .const import (
    ACTIVE_STATES,
    COOLING_TYPES,
    STATUS_KEYS,
    TEMPERATURE_NONE_THRESHOLD,
    MieleStatus,
)


def _get(data: Any, *path: Any, default: Any = None) -> Any:
    for key in path:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and isinstance(key, int):
            data = data[key] if -len(data) <= key < len(data) else None
        else:
            return default
        if data is None:
            return default
    return data


def _minutes(value: Any) -> int | None:
    """Convert [hours, minutes] to minutes."""
    if isinstance(value, list) and len(value) >= 2:
        try:
            return int(value[0]) * 60 + int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _temperature(entry: Any) -> float | None:
    if not isinstance(entry, dict):
        return None
    raw = entry.get("value_raw")
    if raw is None:
        return None
    try:
        raw = int(raw)
    except (TypeError, ValueError):
        return None
    if raw <= TEMPERATURE_NONE_THRESHOLD:
        return None
    return raw / 100


@dataclass
class MieleDevice:
    """A single appliance."""

    serial: str
    raw: dict[str, Any]
    actions: dict[str, Any] = field(default_factory=dict)
    actions_updated: float = 0.0
    programs: list[dict[str, Any]] = field(default_factory=list)
    programs_loaded: bool = False
    filling_levels: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- ident

    @property
    def ident(self) -> dict[str, Any]:
        return self.raw.get("ident") or {}

    @property
    def state(self) -> dict[str, Any]:
        return self.raw.get("state") or {}

    @property
    def type_raw(self) -> int | None:
        return _get(self.ident, "type", "value_raw")

    @property
    def type_name(self) -> str:
        return _get(self.ident, "type", "value_localized") or "Miele appliance"

    @property
    def name(self) -> str:
        return self.ident.get("deviceName") or self.type_name

    @property
    def model(self) -> str | None:
        return _get(self.ident, "deviceIdentLabel", "techType")

    @property
    def sw_version(self) -> str | None:
        return _get(self.ident, "xkmIdentLabel", "releaseVersion")

    @property
    def hw_version(self) -> str | None:
        return _get(self.ident, "xkmIdentLabel", "techType")

    @property
    def is_cooling(self) -> bool:
        return self.type_raw in COOLING_TYPES

    # ------------------------------------------------------------ status

    @property
    def status_raw(self) -> int | None:
        return _get(self.state, "status", "value_raw")

    @property
    def status_key(self) -> str | None:
        raw = self.status_raw
        if raw is None:
            return None
        return STATUS_KEYS.get(raw, "unknown")

    @property
    def status_localized(self) -> str | None:
        return _get(self.state, "status", "value_localized")

    @property
    def is_connected(self) -> bool:
        return self.status_raw not in (None, MieleStatus.NOT_CONNECTED)

    @property
    def is_running(self) -> bool:
        return self.status_raw == MieleStatus.RUNNING

    @property
    def is_active(self) -> bool:
        return self.status_raw in ACTIVE_STATES

    @property
    def is_on(self) -> bool:
        return self.status_raw not in (
            None,
            MieleStatus.OFF,
            MieleStatus.NOT_CONNECTED,
        )

    # ----------------------------------------------------------- program

    @property
    def program_id(self) -> int | None:
        value = _get(self.state, "ProgramID", "value_raw")
        return None if value in (None, 0, -1) else value

    @property
    def program_name(self) -> str | None:
        if self.program_id is None:
            return None
        return _get(self.state, "ProgramID", "value_localized") or None

    @property
    def program_type(self) -> str | None:
        return _get(self.state, "programType", "value_localized") or None

    @property
    def program_phase_raw(self) -> int | None:
        return _get(self.state, "programPhase", "value_raw")

    @property
    def program_phase(self) -> str | None:
        return _get(self.state, "programPhase", "value_localized") or None

    @property
    def remaining_minutes(self) -> int | None:
        return _minutes(self.state.get("remainingTime"))

    @property
    def elapsed_minutes(self) -> int | None:
        return _minutes(self.state.get("elapsedTime"))

    @property
    def start_delay_minutes(self) -> int | None:
        return _minutes(self.state.get("startTime"))

    @property
    def progress(self) -> int | None:
        remaining = self.remaining_minutes
        elapsed = self.elapsed_minutes
        if remaining is None or elapsed is None:
            return None
        if self.status_raw == MieleStatus.PROGRAM_ENDED:
            return 100
        if not self.is_active:
            return None
        total = remaining + elapsed
        if total <= 0:
            return None
        return max(0, min(100, round(elapsed * 100 / total)))

    @property
    def spin_speed(self) -> int | None:
        value = _get(self.state, "spinningSpeed", "value_raw")
        return value if isinstance(value, int) and value > 0 else None

    @property
    def drying_step(self) -> str | None:
        value = _get(self.state, "dryingStep", "value_raw")
        if value is None or value == 65535:
            return None
        return _get(self.state, "dryingStep", "value_localized") or None

    @property
    def ventilation_step(self) -> int | None:
        value = _get(self.state, "ventilationStep", "value_raw")
        return value if isinstance(value, int) else None

    @property
    def plate_steps(self) -> list[int | None]:
        plates = self.state.get("plateStep") or []
        return [p.get("value_raw") if isinstance(p, dict) else None for p in plates]

    # ------------------------------------------------------- temperatures

    def temperature(self, zone: int) -> float | None:
        return _temperature(_get(self.state, "temperature", zone))

    def target_temperature(self, zone: int) -> float | None:
        return _temperature(_get(self.state, "targetTemperature", zone))

    @property
    def core_temperature(self) -> float | None:
        return _temperature(_get(self.state, "coreTemperature", 0))

    @property
    def core_target_temperature(self) -> float | None:
        return _temperature(_get(self.state, "coreTargetTemperature", 0))

    def temperature_zones(self) -> list[int]:
        temps = self.state.get("temperature") or []
        return [i for i, t in enumerate(temps) if _temperature(t) is not None]

    def target_temperature_zones(self) -> list[int]:
        temps = self.state.get("targetTemperature") or []
        return [i for i, t in enumerate(temps) if _temperature(t) is not None]

    # ------------------------------------------------------------ signals

    @property
    def signal_info(self) -> bool | None:
        return self.state.get("signalInfo")

    @property
    def signal_failure(self) -> bool | None:
        return self.state.get("signalFailure")

    @property
    def signal_door(self) -> bool | None:
        return self.state.get("signalDoor")

    @property
    def full_remote_control(self) -> bool | None:
        return _get(self.state, "remoteEnable", "fullRemoteControl")

    @property
    def smart_grid(self) -> bool | None:
        return _get(self.state, "remoteEnable", "smartGrid")

    @property
    def mobile_start(self) -> bool | None:
        return _get(self.state, "remoteEnable", "mobileStart")

    @property
    def light_on(self) -> bool | None:
        value = self.state.get("light")
        if value == 1:
            return True
        if value == 2:
            return False
        return None

    @property
    def ambient_light_on(self) -> bool | None:
        value = self.state.get("ambientLight")
        if value == 1:
            return True
        if value == 2:
            return False
        return None

    @property
    def battery_level(self) -> int | None:
        value = self.state.get("batteryLevel")
        return value if isinstance(value, int) else None

    # ------------------------------------------------------- eco feedback

    @property
    def energy_consumption(self) -> float | None:
        return _get(self.state, "ecoFeedback", "currentEnergyConsumption", "value")

    @property
    def water_consumption(self) -> float | None:
        return _get(self.state, "ecoFeedback", "currentWaterConsumption", "value")

    @property
    def energy_forecast(self) -> int | None:
        value = _get(self.state, "ecoFeedback", "energyForecast")
        return None if value is None else round(float(value) * 100)

    @property
    def water_forecast(self) -> int | None:
        value = _get(self.state, "ecoFeedback", "waterForecast")
        return None if value is None else round(float(value) * 100)

    # ------------------------------------------------------------ actions

    def process_actions(self) -> list[int]:
        return list(self.actions.get("processAction") or [])

    def can(self, action: str) -> bool:
        """Return whether an action key is currently allowed."""
        value = self.actions.get(action)
        if isinstance(value, bool):
            return value
        return bool(value)

    def target_temperature_limits(self, zone: int) -> tuple[float, float] | None:
        for entry in self.actions.get("targetTemperature") or []:
            if isinstance(entry, dict) and entry.get("zone") == zone + 1:
                try:
                    return float(entry["min"]), float(entry["max"])
                except (KeyError, TypeError, ValueError):
                    return None
        return None

    def filling_level(self, key: str) -> int | float | None:
        value = self.filling_levels.get(key)
        return value if isinstance(value, int | float) and not isinstance(value, bool) else None

    @property
    def actions_age(self) -> float:
        return time.monotonic() - self.actions_updated
