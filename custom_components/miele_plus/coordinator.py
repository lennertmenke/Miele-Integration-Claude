"""Data coordinator combining the push stream with an adaptive polling fallback."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import random
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MieleApi, MieleApiError, MieleAuthError, MieleRequestError
from .const import (
    ACTIONS_MAX_AGE,
    ACTIVE_POLL_INTERVAL,
    ACTIVE_STATES,
    CONF_POLL_INTERVAL,
    CONF_POWER_OFF_DELAY,
    CONF_POWER_OFF_ON_FINISH,
    CONF_STALE_GRACE,
    CONF_USE_PUSH,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POWER_OFF_DELAY,
    DEFAULT_POWER_OFF_ON_FINISH,
    DEFAULT_STALE_GRACE,
    DEFAULT_USE_PUSH,
    DISHWASHER_TYPES,
    DOMAIN,
    EVENT_DOOR_CLOSED,
    EVENT_DOOR_OPENED,
    EVENT_FAILURE,
    EVENT_INFO,
    EVENT_MIELE,
    EVENT_PROGRAM_ABORTED,
    EVENT_PROGRAM_FINISHED,
    EVENT_PROGRAM_PAUSED,
    EVENT_PROGRAM_RESUMED,
    EVENT_PROGRAM_STARTED,
    FILLING_LEVELS_INTERVAL,
    HEALTHY_PUSH_POLL_INTERVAL,
    LAUNDRY_TYPES,
    PROGRAM_TYPES,
    SIGNAL_DEVICE_EVENT,
    SSE_BACKOFF_MAX,
    SSE_BACKOFF_MIN,
    SSE_WATCHDOG_TIMEOUT,
    MieleStatus,
)
from .models import MieleDevice

_LOGGER = logging.getLogger(__name__)

type MieleConfigEntry = ConfigEntry[MieleCoordinator]

ACTIONS_DEBOUNCE = 2.0
PROGRAMS_RETRY = 600


class MieleCoordinator(DataUpdateCoordinator[dict[str, MieleDevice]]):
    """Keep appliance state up to date via push with polling as safety net."""

    config_entry: MieleConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MieleConfigEntry, api: MieleApi) -> None:
        """Initialize."""
        self._poll_interval = int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=self._poll_interval),
        )
        self.api = api
        self.options_snapshot = dict(entry.options)
        self.use_push: bool = entry.options.get(CONF_USE_PUSH, DEFAULT_USE_PUSH)
        self.power_off_on_finish: bool = entry.options.get(
            CONF_POWER_OFF_ON_FINISH, DEFAULT_POWER_OFF_ON_FINISH
        )
        self.power_off_delay = int(entry.options.get(CONF_POWER_OFF_DELAY, DEFAULT_POWER_OFF_DELAY))
        self._stale_grace = 60 * int(entry.options.get(CONF_STALE_GRACE, DEFAULT_STALE_GRACE))
        self.push_connected = False
        self.push_connected_since: datetime | None = None
        self.last_push_message: datetime | None = None
        self.last_successful_update: datetime | None = None
        self._last_success_mono: float | None = None
        self._push_task: asyncio.Task | None = None
        self._actions_dirty: set[str] = set()
        self._actions_task: asyncio.Task | None = None
        self._programs_tried: dict[str, float] = {}
        self._filling_next = 0.0
        self.stats: dict[str, int] = {
            "polls": 0,
            "poll_errors": 0,
            "stale_updates_served": 0,
            "push_connects": 0,
            "push_disconnects": 0,
            "push_events": 0,
            "actions_fetched": 0,
            "commands_sent": 0,
            "command_errors": 0,
        }
        self.last_error: str | None = None

    # ------------------------------------------------------------ lifecycle

    async def async_start_push(self) -> None:
        """Start the push listener (if enabled)."""
        if not self.use_push or self._push_task is not None:
            return
        self._push_task = self.config_entry.async_create_background_task(
            self.hass, self._push_loop(), f"{DOMAIN}_push_{self.config_entry.entry_id}"
        )

    async def async_shutdown(self) -> None:
        """Stop background tasks."""
        for task in (self._push_task, self._actions_task):
            if task and not task.done():
                task.cancel()
        self._push_task = None
        await super().async_shutdown()

    # ------------------------------------------------------------- polling

    async def _async_update_data(self) -> dict[str, MieleDevice]:
        self.stats["polls"] += 1
        try:
            raw = await self.api.get_devices()
        except MieleAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MieleApiError as err:
            self.stats["poll_errors"] += 1
            self.last_error = str(err)
            if self.data is not None and self._within_grace():
                self.stats["stale_updates_served"] += 1
                _LOGGER.debug("Miele cloud error (%s), keeping last known state", err)
                return self.data
            raise UpdateFailed(f"Error talking to Miele cloud: {err}") from err

        devices = self._merge_devices(raw, full=True)
        await self._refresh_actions(devices)
        await self._refresh_filling_levels(devices)
        self._mark_success()
        self._adjust_interval(devices)
        self._schedule_program_loading(devices)
        return devices

    def _within_grace(self) -> bool:
        if self._last_success_mono is None:
            return False
        return time.monotonic() - self._last_success_mono < self._stale_grace

    def _mark_success(self) -> None:
        self._last_success_mono = time.monotonic()
        self.last_successful_update = dt_util.utcnow()

    @callback
    def _adjust_interval(self, devices: dict[str, MieleDevice] | None = None) -> None:
        devices = devices if devices is not None else (self.data or {})
        if self.push_connected:
            seconds = HEALTHY_PUSH_POLL_INTERVAL
        elif any(d.status_raw in ACTIVE_STATES for d in devices.values()):
            seconds = min(ACTIVE_POLL_INTERVAL, self._poll_interval)
        else:
            seconds = self._poll_interval
        interval = timedelta(seconds=seconds)
        if interval != self.update_interval:
            _LOGGER.debug("Polling interval now %ss", seconds)
            self.update_interval = interval

    async def _refresh_actions(self, devices: dict[str, MieleDevice]) -> None:
        targets = [
            dev
            for serial, dev in devices.items()
            if dev.is_connected
            and (serial in self._actions_dirty or dev.actions_age > ACTIONS_MAX_AGE)
        ]
        if not targets:
            return
        results = await asyncio.gather(
            *(self.api.get_actions(dev.serial) for dev in targets),
            return_exceptions=True,
        )
        for dev, result in zip(targets, results, strict=True):
            if isinstance(result, MieleAuthError):
                raise ConfigEntryAuthFailed(str(result)) from result
            if isinstance(result, BaseException):
                _LOGGER.debug("Could not fetch actions for %s: %s", dev.serial, result)
                continue
            self.stats["actions_fetched"] += 1
            dev.actions = result
            dev.actions_updated = time.monotonic()
            self._actions_dirty.discard(dev.serial)

    async def _refresh_filling_levels(self, devices: dict[str, MieleDevice]) -> None:
        """Fetch consumable levels (not pushed by the stream) with their own cadence."""
        if time.monotonic() < self._filling_next:
            return
        try:
            levels = await self.api.get_filling_levels()
        except MieleAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MieleRequestError as err:
            # Not supported for this account/devices: try again much later
            _LOGGER.debug("Filling levels not available: %s", err)
            self._filling_next = time.monotonic() + 6 * 3600
            return
        except MieleApiError as err:
            _LOGGER.debug("Could not fetch filling levels: %s", err)
            self._filling_next = time.monotonic() + 60
            return
        self._filling_next = time.monotonic() + FILLING_LEVELS_INTERVAL
        for serial, values in levels.items():
            if (dev := devices.get(serial)) is not None:
                dev.filling_levels = values

    @callback
    def _schedule_actions_refresh(self) -> None:
        if self._actions_task and not self._actions_task.done():
            return

        async def _run() -> None:
            await asyncio.sleep(ACTIONS_DEBOUNCE)
            if not self.data:
                return
            try:
                await self._refresh_actions(self.data)
            except ConfigEntryAuthFailed:
                self.config_entry.async_start_reauth(self.hass)
                return
            self.async_update_listeners()

        self._actions_task = self.config_entry.async_create_background_task(
            self.hass, _run(), f"{DOMAIN}_actions"
        )

    # ------------------------------------------------------------ programs

    @callback
    def _schedule_program_loading(self, devices: dict[str, MieleDevice]) -> None:
        now = time.monotonic()
        for dev in devices.values():
            if dev.type_raw not in PROGRAM_TYPES or dev.programs or not dev.is_on:
                continue
            if now - self._programs_tried.get(dev.serial, -PROGRAMS_RETRY) < PROGRAMS_RETRY:
                continue
            self._programs_tried[dev.serial] = now
            self.config_entry.async_create_background_task(
                self.hass, self.async_load_programs(dev.serial), f"{DOMAIN}_programs"
            )

    async def async_load_programs(self, serial: str) -> list[dict[str, Any]]:
        """Fetch remotely startable programs for a device."""
        dev = (self.data or {}).get(serial)
        if dev is None:
            return []
        try:
            programs = await self.api.get_programs(serial)
        except MieleApiError as err:
            _LOGGER.debug("Programs not available for %s: %s", serial, err)
            return dev.programs
        if programs:
            dev.programs = programs
            dev.programs_loaded = True
            self.async_update_listeners()
        return dev.programs

    # ---------------------------------------------------------- merge/diff

    @callback
    def _merge_devices(self, raw: dict[str, Any], *, full: bool) -> dict[str, MieleDevice]:
        """Merge raw payload into the device objects and detect transitions."""
        current = dict(self.data or {})
        for serial, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            existing = current.get(serial)
            if existing is None:
                current[serial] = MieleDevice(serial=serial, raw=payload)
                current[serial].track_elapsed()
                self._actions_dirty.add(serial)
                continue
            old = MieleDevice(serial=serial, raw=existing.raw)
            existing.raw = _deep_merge(existing.raw, payload)
            existing.last_elapsed_minutes = old.last_elapsed_minutes = existing.last_elapsed_minutes
            self._detect_transitions(old, existing)
            existing.track_elapsed()
        if full:
            # Devices removed from the account disappear on full refreshes
            for serial in list(current):
                if serial not in raw:
                    current.pop(serial)
        return current

    @callback
    def _detect_transitions(self, old: MieleDevice, new: MieleDevice) -> None:
        old_status, new_status = old.status_raw, new.status_raw
        if old_status != new_status or old.program_id != new.program_id:
            self._actions_dirty.add(new.serial)
            if old_status in (MieleStatus.OFF, MieleStatus.NOT_CONNECTED, None):
                # Device just came online: programs may be available now
                self._programs_tried.pop(new.serial, None)
        events: list[tuple[str, dict[str, Any]]] = []
        active = (MieleStatus.RUNNING, MieleStatus.PAUSE, MieleStatus.RINSE_HOLD)

        if old_status != new_status:
            if new_status == MieleStatus.RUNNING:
                if old_status == MieleStatus.PAUSE:
                    events.append((EVENT_PROGRAM_RESUMED, {}))
                elif old_status not in active:
                    events.append((EVENT_PROGRAM_STARTED, {}))
            elif new_status == MieleStatus.PAUSE and old_status == MieleStatus.RUNNING:
                events.append((EVENT_PROGRAM_PAUSED, {}))
            elif new_status == MieleStatus.PROGRAM_ENDED and old_status in active:
                self._filling_next = 0.0
                if self.power_off_on_finish and new.type_raw in LAUNDRY_TYPES | DISHWASHER_TYPES:
                    self.config_entry.async_create_background_task(
                        self.hass, self._auto_power_off(new.serial), f"{DOMAIN}_power_off"
                    )
                events.append(
                    (
                        EVENT_PROGRAM_FINISHED,
                        {
                            "duration": old.elapsed_minutes or old.last_elapsed_minutes,
                            "energy_kwh": _first(new.energy_consumption, old.energy_consumption),
                            "water_l": _first(new.water_consumption, old.water_consumption),
                        },
                    )
                )
            elif old_status in active and new_status in (
                MieleStatus.PROGRAM_INTERRUPTED,
                MieleStatus.OFF,
                MieleStatus.ON,
                MieleStatus.IDLE,
            ):
                events.append((EVENT_PROGRAM_ABORTED, {"duration": old.elapsed_minutes}))
            if new_status == MieleStatus.FAILURE:
                events.append((EVENT_FAILURE, {}))

        if new.signal_failure and not old.signal_failure and new_status != MieleStatus.FAILURE:
            events.append((EVENT_FAILURE, {}))
        if new.signal_info and not old.signal_info:
            events.append((EVENT_INFO, {}))
        if old.signal_door is not None and new.signal_door is not None:
            if new.signal_door and not old.signal_door:
                events.append((EVENT_DOOR_OPENED, {}))
            elif old.signal_door and not new.signal_door:
                events.append((EVENT_DOOR_CLOSED, {}))

        for event_type, extra in events:
            data = {
                "device_id": new.serial,
                "device_name": new.name,
                "type": event_type,
                "program": new.program_name or old.program_name,
                "program_id": new.program_id or old.program_id,
                "status": new.status_key,
                **extra,
            }
            _LOGGER.debug("Miele event for %s: %s", new.serial, data)
            self.hass.bus.async_fire(EVENT_MIELE, data)
            async_dispatcher_send(
                self.hass, SIGNAL_DEVICE_EVENT.format(new.serial), event_type, data
            )

    # ---------------------------------------------------------------- push

    async def _push_loop(self) -> None:
        backoff = SSE_BACKOFF_MIN
        while True:
            started = time.monotonic()
            reason: str
            try:
                await self.api.listen_events(
                    self._handle_push_event,
                    watchdog=SSE_WATCHDOG_TIMEOUT,
                    on_connect=self._on_push_connected,
                )
                reason = "stream closed by server"
            except MieleAuthError as err:
                _LOGGER.warning("Miele push authentication failed: %s", err)
                self._set_push_state(False)
                self.config_entry.async_start_reauth(self.hass)
                return
            except MieleApiError as err:
                reason = str(err)
            except asyncio.CancelledError:
                self._set_push_state(False)
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Unexpected error in Miele push stream")
                reason = repr(err)

            was_connected = self.push_connected
            self._set_push_state(False)
            if time.monotonic() - started > 120:
                backoff = SSE_BACKOFF_MIN
            delay = backoff + random.uniform(0, backoff / 2)
            log = _LOGGER.info if was_connected else _LOGGER.debug
            log("Miele push stream lost (%s), reconnecting in %.0fs", reason, delay)
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, SSE_BACKOFF_MAX)

    @callback
    def _on_push_connected(self) -> None:
        _LOGGER.debug("Miele push stream connected")
        self.stats["push_connects"] += 1
        self._set_push_state(True)
        # Catch up on anything missed while disconnected
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _set_push_state(self, connected: bool) -> None:
        if connected == self.push_connected:
            return
        self.push_connected = connected
        if connected:
            self.push_connected_since = dt_util.utcnow()
        else:
            self.stats["push_disconnects"] += 1
            self.push_connected_since = None
        self._adjust_interval()
        if not connected and self.data is not None:
            # Make sure polling takes over right away instead of in 10 minutes
            self.hass.async_create_task(self.async_request_refresh())
        self.async_update_listeners()

    @callback
    def _handle_push_event(self, event: str, payload: Any) -> None:
        self.last_push_message = dt_util.utcnow()
        if event == "ping":
            return
        self.stats["push_events"] += 1
        if event == "devices" and isinstance(payload, dict):
            devices = self._merge_devices(payload, full=False)
            self._mark_success()
            self._adjust_interval(devices)
            self.async_set_updated_data(devices)
            self._schedule_program_loading(devices)
            if self._actions_dirty:
                self._schedule_actions_refresh()
        elif event == "actions" and isinstance(payload, dict) and self.data:
            now = time.monotonic()
            for serial, actions in payload.items():
                dev = self.data.get(serial)
                if dev is not None and isinstance(actions, dict):
                    dev.actions = actions
                    dev.actions_updated = now
                    self._actions_dirty.discard(serial)
            self.async_update_listeners()

    # ------------------------------------------------------------ commands

    async def _auto_power_off(self, serial: str) -> None:
        """Switch the appliance off after the program ended (silences the end buzzer)."""
        await asyncio.sleep(max(self.power_off_delay, 1))
        for attempt in range(1, 4):
            dev = (self.data or {}).get(serial)
            if dev is None or dev.status_raw != MieleStatus.PROGRAM_ENDED:
                _LOGGER.debug("Auto power-off for %s skipped: status changed", serial)
                return
            try:
                await self.api.send_action(serial, {"powerOff": True})
            except MieleAuthError:
                self.config_entry.async_start_reauth(self.hass)
                return
            except MieleApiError as err:
                _LOGGER.debug("Auto power-off attempt %s for %s failed: %s", attempt, serial, err)
                await asyncio.sleep(10 * attempt)
                continue
            _LOGGER.info("Switched off %s after the program ended", dev.name)
            self.stats["auto_power_off"] = self.stats.get("auto_power_off", 0) + 1
            self._actions_dirty.add(serial)
            if not self.push_connected:
                await self.async_request_refresh()
            return
        _LOGGER.warning(
            "Could not switch off %s after the program ended (remote control enabled?)", serial
        )

    async def async_send_action(self, serial: str, body: dict[str, Any]) -> None:
        """Send an action and refresh state afterwards."""
        await self._command(self.api.send_action, serial, body)

    async def async_start_program(self, serial: str, body: dict[str, Any]) -> None:
        """Start a program and refresh state afterwards."""
        await self._command(self.api.start_program, serial, body)

    async def _command(self, func: Any, serial: str, body: dict[str, Any]) -> None:
        self.stats["commands_sent"] += 1
        try:
            await func(serial, body)
        except MieleAuthError as err:
            self.stats["command_errors"] += 1
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"Miele authentication failed: {err}") from err
        except MieleRequestError as err:
            self.stats["command_errors"] += 1
            raise HomeAssistantError(
                f"Miele rejected the command {body}: {err.message} "
                "(is remote control enabled on the appliance?)"
            ) from err
        except MieleApiError as err:
            self.stats["command_errors"] += 1
            raise HomeAssistantError(f"Could not reach Miele cloud: {err}") from err
        self._actions_dirty.add(serial)
        if self.push_connected:
            self._schedule_actions_refresh()
        else:
            await self.async_request_refresh()


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge update into a copy of base (nested dicts merged, other values replaced)."""
    result = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None
