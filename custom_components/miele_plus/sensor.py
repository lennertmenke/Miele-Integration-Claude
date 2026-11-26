"""Sensor platform for Miele Plus."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util

from .const import (
    COOLING_TYPES,
    DRYER_TYPES,
    ECO_TYPES,
    HOB_TYPES,
    OVEN_TYPES,
    PROGRAM_STATES,
    PROGRAM_TYPES,
    STATUS_KEYS,
    WASHER_TYPES,
    DeviceType,
    MieleStatus,
)
from .coordinator import MieleConfigEntry, MieleCoordinator
from .entity import MieleEntity, MieleEntityDescription, async_setup_device_entities
from .models import MieleDevice

PARALLEL_UPDATES = 0

STATUS_OPTIONS = sorted({*STATUS_KEYS.values(), "unknown"})


@dataclass(frozen=True, kw_only=True)
class MieleSensorDescription(MieleEntityDescription, SensorEntityDescription):
    """Describes a Miele sensor."""

    value_fn: Callable[[MieleDevice], Any]
    attr_fn: Callable[[MieleDevice], dict[str, Any]] | None = None
    always_available: bool = False


def _in_program(dev: MieleDevice, value: Any, idle: Any = 0) -> Any:
    return value if dev.status_raw in PROGRAM_STATES else idle


SENSORS: tuple[MieleSensorDescription, ...] = (
    MieleSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value_fn=lambda d: d.status_key,
        attr_fn=lambda d: {
            "status_raw": d.status_raw,
            "status_localized": d.status_localized,
        },
        always_available=True,
    ),
    MieleSensorDescription(
        key="program",
        translation_key="program",
        exists_fn=lambda d: d.type_raw in PROGRAM_TYPES,
        value_fn=lambda d: d.program_name,
        attr_fn=lambda d: {"program_id": d.program_id, "program_type": d.program_type},
    ),
    MieleSensorDescription(
        key="program_phase",
        translation_key="program_phase",
        exists_fn=lambda d: d.type_raw in PROGRAM_TYPES,
        value_fn=lambda d: _in_program(d, d.program_phase, None),
        attr_fn=lambda d: {"program_phase_raw": d.program_phase_raw},
    ),
    MieleSensorDescription(
        key="remaining_time",
        translation_key="remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda d: d.type_raw in PROGRAM_TYPES,
        value_fn=lambda d: _in_program(d, d.remaining_minutes),
    ),
    MieleSensorDescription(
        key="elapsed_time",
        translation_key="elapsed_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda d: d.type_raw in PROGRAM_TYPES,
        value_fn=lambda d: _in_program(d, d.elapsed_minutes),
    ),
    MieleSensorDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda d: d.type_raw in PROGRAM_TYPES,
        value_fn=lambda d: d.progress if d.progress is not None else 0,
    ),
    MieleSensorDescription(
        key="spin_speed",
        translation_key="spin_speed",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        exists_fn=lambda d: d.type_raw in WASHER_TYPES,
        value_fn=lambda d: _in_program(d, d.spin_speed, None),
    ),
    MieleSensorDescription(
        key="drying_step",
        translation_key="drying_step",
        exists_fn=lambda d: d.type_raw in DRYER_TYPES,
        value_fn=lambda d: _in_program(d, d.drying_step, None),
    ),
    MieleSensorDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        exists_fn=lambda d: d.type_raw in OVEN_TYPES | WASHER_TYPES | DRYER_TYPES,
        value_fn=lambda d: d.target_temperature(0),
    ),
    MieleSensorDescription(
        key="core_temperature",
        translation_key="core_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda d: d.type_raw in OVEN_TYPES and "coreTemperature" in d.state,
        value_fn=lambda d: d.core_temperature,
    ),
    MieleSensorDescription(
        key="core_target_temperature",
        translation_key="core_target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        exists_fn=lambda d: d.type_raw in OVEN_TYPES and "coreTargetTemperature" in d.state,
        value_fn=lambda d: d.core_target_temperature,
    ),
    MieleSensorDescription(
        key="ventilation_step",
        translation_key="ventilation_step",
        exists_fn=lambda d: d.type_raw == DeviceType.HOOD,
        value_fn=lambda d: d.ventilation_step,
    ),
    MieleSensorDescription(
        key="energy_consumption",
        translation_key="energy_consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        exists_fn=lambda d: d.type_raw in ECO_TYPES,
        value_fn=lambda d: d.energy_consumption,
    ),
    MieleSensorDescription(
        key="water_consumption",
        translation_key="water_consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        exists_fn=lambda d: d.type_raw in ECO_TYPES,
        value_fn=lambda d: d.water_consumption,
    ),
    MieleSensorDescription(
        key="energy_forecast",
        translation_key="energy_forecast",
        native_unit_of_measurement=PERCENTAGE,
        exists_fn=lambda d: d.type_raw in ECO_TYPES,
        value_fn=lambda d: d.energy_forecast,
    ),
    MieleSensorDescription(
        key="water_forecast",
        translation_key="water_forecast",
        native_unit_of_measurement=PERCENTAGE,
        exists_fn=lambda d: d.type_raw in ECO_TYPES,
        value_fn=lambda d: d.water_forecast,
    ),
    MieleSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda d: d.type_raw == DeviceType.ROBOT_VACUUM_CLEANER,
        value_fn=lambda d: d.battery_level,
    ),
)

FILLING_SENSORS: tuple[MieleSensorDescription, ...] = tuple(
    MieleSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=category,
        exists_fn=lambda d, raw=raw: d.filling_level(raw) is not None,
        value_fn=lambda d, raw=raw: d.filling_level(raw),
        always_available=True,
    )
    for key, raw, category in (
        ("twin_dos_1_level", "twinDosContainer1FillingLevel", None),
        ("twin_dos_2_level", "twinDosContainer2FillingLevel", None),
        ("power_disc_level", "powerDiscFillingLevel", None),
        ("salt_level", "saltFillingLevel", None),
        ("rinse_aid_level", "rinseAidFillingLevel", None),
        ("coal_filter_saturation", "coalFilterSaturation", EntityCategory.DIAGNOSTIC),
        ("fat_filter_saturation", "fatFilterSaturation", EntityCategory.DIAGNOSTIC),
    )
)

TOTAL_SENSORS: tuple[MieleSensorDescription, ...] = (
    MieleSensorDescription(
        key="energy_total",
        translation_key="energy_total",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        exists_fn=lambda d: d.type_raw in ECO_TYPES,
        value_fn=lambda d: d.energy_consumption,
        always_available=True,
    ),
    MieleSensorDescription(
        key="water_total",
        translation_key="water_total",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=lambda d: d.type_raw in ECO_TYPES,
        value_fn=lambda d: d.water_consumption,
        always_available=True,
    ),
)

TEMPERATURE_DESCRIPTION = MieleSensorDescription(
    key="temperature",
    translation_key="temperature",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    value_fn=lambda d: d.temperature(0),
)

PLATE_DESCRIPTION = MieleSensorDescription(
    key="plate",
    translation_key="plate",
    value_fn=lambda d: None,
)

FINISH_DESCRIPTION = MieleSensorDescription(
    key="finish_time",
    translation_key="finish_time",
    device_class=SensorDeviceClass.TIMESTAMP,
    exists_fn=lambda d: d.type_raw in PROGRAM_TYPES,
    value_fn=lambda d: None,
)

START_DESCRIPTION = MieleSensorDescription(
    key="start_time",
    translation_key="start_time",
    device_class=SensorDeviceClass.TIMESTAMP,
    exists_fn=lambda d: d.type_raw in PROGRAM_TYPES,
    value_fn=lambda d: None,
)

CONNECTION_DESCRIPTION = MieleSensorDescription(
    key="update_mode",
    translation_key="update_mode",
    device_class=SensorDeviceClass.ENUM,
    options=["push", "polling"],
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda d: None,
    always_available=True,
)

LAST_UPDATE_DESCRIPTION = MieleSensorDescription(
    key="last_update",
    translation_key="last_update",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda d: None,
    always_available=True,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MieleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data

    def _factory(dev: MieleDevice) -> Iterable[MieleEntity]:
        for desc in SENSORS:
            if desc.exists_fn(dev):
                yield MieleSensor(coordinator, dev.serial, desc)
        for desc in FILLING_SENSORS:
            if desc.exists_fn(dev):
                yield MieleSensor(coordinator, dev.serial, desc)
        for desc in TOTAL_SENSORS:
            if desc.exists_fn(dev):
                yield MieleTotalSensor(coordinator, dev.serial, desc)
        zones = set(dev.temperature_zones())
        if dev.type_raw in OVEN_TYPES | COOLING_TYPES:
            zones.add(0)
        for zone in sorted(zones):
            yield MieleTemperatureSensor(coordinator, dev.serial, zone)
        if dev.type_raw in HOB_TYPES:
            for idx in range(len(dev.plate_steps)):
                yield MielePlateSensor(coordinator, dev.serial, idx)
        if FINISH_DESCRIPTION.exists_fn(dev):
            yield MieleFinishTimeSensor(coordinator, dev.serial, FINISH_DESCRIPTION)
            yield MieleStartTimeSensor(coordinator, dev.serial, START_DESCRIPTION)
        yield MieleUpdateModeSensor(coordinator, dev.serial, CONNECTION_DESCRIPTION)
        yield MieleLastUpdateSensor(coordinator, dev.serial, LAST_UPDATE_DESCRIPTION)

    async_setup_device_entities(coordinator, entry, async_add_entities, _factory)


class MieleSensor(MieleEntity, SensorEntity):
    """Generic Miele sensor."""

    entity_description: MieleSensorDescription

    def __init__(
        self,
        coordinator: MieleCoordinator,
        serial: str,
        description: MieleSensorDescription,
        suffix: str | None = None,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, serial, description, suffix)
        self._always_available = description.always_available

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.device)


class MieleTemperatureSensor(MieleSensor):
    """Temperature of a zone."""

    def __init__(self, coordinator: MieleCoordinator, serial: str, zone: int) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            serial,
            TEMPERATURE_DESCRIPTION,
            None if zone == 0 else str(zone + 1),
        )
        self._zone = zone
        if zone > 0:
            self._attr_translation_key = "temperature_zone"
            self._attr_translation_placeholders = {"zone": str(zone + 1)}

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        return self.device.temperature(self._zone)


class MielePlateSensor(MieleSensor):
    """Power step of a hob cooking zone."""

    def __init__(self, coordinator: MieleCoordinator, serial: str, idx: int) -> None:
        """Initialize."""
        super().__init__(coordinator, serial, PLATE_DESCRIPTION, str(idx + 1))
        self._idx = idx
        self._attr_translation_placeholders = {"plate": str(idx + 1)}

    @property
    def native_value(self) -> int | None:
        """Return the step."""
        steps = self.device.plate_steps
        return steps[self._idx] if self._idx < len(steps) else None


class _StableTimestampSensor(MieleSensor):
    """Timestamp that only moves when the computed time drifts noticeably.

    Remaining time has minute resolution, so a naively computed end time would
    jitter by up to a minute on every update and spam the recorder.
    """

    _tolerance = timedelta(seconds=90)

    def __init__(self, *args: Any) -> None:
        """Initialize."""
        super().__init__(*args)
        self._value: datetime | None = None

    def _compute(self, dev: MieleDevice) -> datetime | None:
        raise NotImplementedError

    @callback
    def _update_value(self) -> None:
        if self._serial not in (self.coordinator.data or {}):
            return
        new = self._compute(self.device)
        if new is None or self._value is None or abs(new - self._value) > self._tolerance:
            self._value = new

    async def async_added_to_hass(self) -> None:
        """Compute initial value."""
        await super().async_added_to_hass()
        self._update_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> datetime | None:
        """Return the timestamp."""
        return self._value


class MieleFinishTimeSensor(_StableTimestampSensor):
    """Estimated end of the running/scheduled program."""

    def _compute(self, dev: MieleDevice) -> datetime | None:
        remaining = dev.remaining_minutes
        if dev.status_raw not in PROGRAM_STATES or not remaining:
            return None
        if dev.status_raw == MieleStatus.PROGRAM_ENDED:
            return None
        delay = 0
        if dev.status_raw in (MieleStatus.PROGRAMMED, MieleStatus.WAITING_TO_START):
            delay = dev.start_delay_minutes or 0
        return (dt_util.utcnow() + timedelta(minutes=delay + remaining)).replace(
            second=0, microsecond=0
        )


class MieleStartTimeSensor(_StableTimestampSensor):
    """Start time of a delayed program."""

    def _compute(self, dev: MieleDevice) -> datetime | None:
        delay = dev.start_delay_minutes
        if dev.status_raw != MieleStatus.WAITING_TO_START or not delay:
            return None
        return (dt_util.utcnow() + timedelta(minutes=delay)).replace(second=0, microsecond=0)


class MieleUpdateModeSensor(MieleSensor):
    """Whether the integration currently receives push updates."""

    @property
    def native_value(self) -> str:
        """Return push/polling."""
        return "push" if self.coordinator.push_connected else "polling"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose connection statistics."""
        coord = self.coordinator
        return {
            "push_enabled": coord.use_push,
            "push_connected_since": coord.push_connected_since,
            "last_push_message": coord.last_push_message,
            "poll_interval": int(coord.update_interval.total_seconds())
            if coord.update_interval
            else None,
            "last_error": coord.last_error,
            **coord.stats,
        }


class MieleLastUpdateSensor(MieleSensor):
    """Time of the last successful data update."""

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp."""
        return self.coordinator.last_successful_update


@dataclass
class _TotalData(ExtraStoredData):
    last_program_value: float | None

    def as_dict(self) -> dict[str, Any]:
        return {"last_program_value": self.last_program_value}


class MieleTotalSensor(MieleEntity, RestoreSensor):
    """Lifetime consumption accumulated across programs (for the energy dashboard)."""

    entity_description: MieleSensorDescription

    def __init__(
        self,
        coordinator: MieleCoordinator,
        serial: str,
        description: MieleSensorDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, serial, description)
        self._always_available = True
        self._total: float = 0.0
        self._last: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the running total."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            try:
                self._total = float(last.native_value or 0)
            except (TypeError, ValueError):
                self._total = 0.0
        if (extra := await self.async_get_last_extra_data()) is not None:
            value = extra.as_dict().get("last_program_value")
            self._last = float(value) if value is not None else None
        self._accumulate()

    @property
    def extra_restore_state_data(self) -> _TotalData:
        """Persist the per-program baseline."""
        return _TotalData(self._last)

    @callback
    def _accumulate(self) -> None:
        if self._serial not in (self.coordinator.data or {}):
            return
        value = self.entity_description.value_fn(self.device)
        if value is None:
            return
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if self._last is None:
            # First observation: we don't know what happened before
            self._last = value
            return
        if value >= self._last:
            self._total += value - self._last
        else:
            # Counter reset -> a new program started
            self._total += value
        self._last = value

    @callback
    def _handle_coordinator_update(self) -> None:
        self._accumulate()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        """Return the total."""
        return round(self._total, 3)
