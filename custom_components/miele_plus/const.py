"""Constants for the Miele Plus integration."""

from __future__ import annotations

from enum import IntEnum
from typing import Final

DOMAIN: Final = "miele_plus"
MANUFACTURER: Final = "Miele"

OAUTH2_AUTHORIZE: Final = (
    "https://auth.domestic.miele-iot.com/partner/realms/mcs/protocol/openid-connect/auth"
)
OAUTH2_TOKEN: Final = (
    "https://auth.domestic.miele-iot.com/partner/realms/mcs/protocol/openid-connect/token"
)
API_BASE: Final = "https://api.mcs3.miele.com/v1"
OAUTH2_SCOPES: Final = (
    "openid",
    "mcs_thirdparty_read",
    "mcs_thirdparty_write",
    "mcs_thirdparty_media",
)
# Filling levels are not part of the event stream; refresh them this often (s)
FILLING_LEVELS_INTERVAL: Final = 600

# Options
CONF_LANGUAGE: Final = "language"
CONF_USE_PUSH: Final = "use_push"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_STALE_GRACE: Final = "stale_grace"
CONF_POWER_OFF_ON_FINISH: Final = "power_off_on_finish"
CONF_POWER_OFF_DELAY: Final = "power_off_delay"

DEFAULT_LANGUAGE: Final = "auto"
DEFAULT_USE_PUSH: Final = True
DEFAULT_POLL_INTERVAL: Final = 60  # seconds, used while push is unavailable
DEFAULT_STALE_GRACE: Final = 15  # minutes to keep last known state on errors
DEFAULT_POWER_OFF_ON_FINISH: Final = False
DEFAULT_POWER_OFF_DELAY: Final = 0  # seconds after the end of a program

# Polling while the push stream is healthy (safety net against missed events)
HEALTHY_PUSH_POLL_INTERVAL: Final = 600
# Polling while push is down and at least one appliance is running
ACTIVE_POLL_INTERVAL: Final = 30
# Reconnect stream if nothing (not even a ping) arrived for this long
SSE_WATCHDOG_TIMEOUT: Final = 90
SSE_BACKOFF_MIN: Final = 5
SSE_BACKOFF_MAX: Final = 300
# Refresh the actions of every device at least this often (seconds)
ACTIONS_MAX_AGE: Final = 900

EVENT_MIELE: Final = f"{DOMAIN}_event"
SIGNAL_DEVICE_EVENT: Final = f"{DOMAIN}_device_event_{{}}"

TEMPERATURE_NONE_THRESHOLD: Final = -32760


class MieleStatus(IntEnum):
    """Appliance status codes as reported by the Miele 3rd-party API."""

    OFF = 1
    ON = 2
    PROGRAMMED = 3
    WAITING_TO_START = 4
    RUNNING = 5
    PAUSE = 6
    PROGRAM_ENDED = 7
    FAILURE = 8
    PROGRAM_INTERRUPTED = 9
    IDLE = 10
    RINSE_HOLD = 11
    SERVICE = 12
    SUPERFREEZING = 13
    SUPERCOOLING = 14
    SUPERHEATING = 15
    DEFAULT = 144
    LOCKED = 145
    SUPERCOOLING_SUPERFREEZING = 146
    NOT_CONNECTED = 255


STATUS_KEYS: Final[dict[int, str]] = {
    MieleStatus.OFF: "off",
    MieleStatus.ON: "on",
    MieleStatus.PROGRAMMED: "programmed",
    MieleStatus.WAITING_TO_START: "waiting_to_start",
    MieleStatus.RUNNING: "running",
    MieleStatus.PAUSE: "pause",
    MieleStatus.PROGRAM_ENDED: "program_ended",
    MieleStatus.FAILURE: "failure",
    MieleStatus.PROGRAM_INTERRUPTED: "program_interrupted",
    MieleStatus.IDLE: "idle",
    MieleStatus.RINSE_HOLD: "rinse_hold",
    MieleStatus.SERVICE: "service",
    MieleStatus.SUPERFREEZING: "superfreezing",
    MieleStatus.SUPERCOOLING: "supercooling",
    MieleStatus.SUPERHEATING: "superheating",
    MieleStatus.DEFAULT: "default",
    MieleStatus.LOCKED: "locked",
    MieleStatus.SUPERCOOLING_SUPERFREEZING: "supercooling_superfreezing",
    MieleStatus.NOT_CONNECTED: "not_connected",
}

# States in which a program is considered active
ACTIVE_STATES: Final = frozenset(
    {
        MieleStatus.RUNNING,
        MieleStatus.PAUSE,
        MieleStatus.RINSE_HOLD,
    }
)
# States in which a program is selected/scheduled or running
PROGRAM_STATES: Final = ACTIVE_STATES | {
    MieleStatus.PROGRAMMED,
    MieleStatus.WAITING_TO_START,
    MieleStatus.PROGRAM_ENDED,
}


class ProcessAction(IntEnum):
    """Values for the processAction command."""

    START = 1
    STOP = 2
    PAUSE = 3
    START_SUPERFREEZING = 4
    STOP_SUPERFREEZING = 5
    START_SUPERCOOLING = 6
    STOP_SUPERCOOLING = 7


class DeviceType(IntEnum):
    """Appliance type codes."""

    WASHING_MACHINE = 1
    TUMBLE_DRYER = 2
    WASHING_MACHINE_SEMI_PRO = 3
    TUMBLE_DRYER_SEMI_PRO = 4
    WASHING_MACHINE_PRO = 5
    DRYER_PRO = 6
    DISHWASHER = 7
    DISHWASHER_SEMI_PRO = 8
    DISHWASHER_PRO = 9
    OVEN = 12
    OVEN_MICROWAVE = 13
    HOB_HIGHLIGHT = 14
    STEAM_OVEN = 15
    MICROWAVE = 16
    COFFEE_SYSTEM = 17
    HOOD = 18
    FRIDGE = 19
    FREEZER = 20
    FRIDGE_FREEZER = 21
    ROBOT_VACUUM_CLEANER = 23
    WASHER_DRYER = 24
    DISH_WARMER = 25
    HOB_INDUCTION = 27
    STEAM_OVEN_COMBI = 31
    WINE_CABINET = 32
    WINE_CONDITIONING_UNIT = 33
    WINE_STORAGE_CONDITIONING_UNIT = 34
    STEAM_OVEN_MICRO = 45
    DIALOG_OVEN = 67
    WINE_CABINET_FREEZER = 68
    STEAM_OVEN_MK2 = 73
    HOB_INDUCT_EXTR = 74


LAUNDRY_TYPES: Final = frozenset(
    {
        DeviceType.WASHING_MACHINE,
        DeviceType.TUMBLE_DRYER,
        DeviceType.WASHING_MACHINE_SEMI_PRO,
        DeviceType.TUMBLE_DRYER_SEMI_PRO,
        DeviceType.WASHING_MACHINE_PRO,
        DeviceType.DRYER_PRO,
        DeviceType.WASHER_DRYER,
    }
)
WASHER_TYPES: Final = frozenset(
    {
        DeviceType.WASHING_MACHINE,
        DeviceType.WASHING_MACHINE_SEMI_PRO,
        DeviceType.WASHING_MACHINE_PRO,
        DeviceType.WASHER_DRYER,
    }
)
DRYER_TYPES: Final = frozenset(
    {
        DeviceType.TUMBLE_DRYER,
        DeviceType.TUMBLE_DRYER_SEMI_PRO,
        DeviceType.DRYER_PRO,
        DeviceType.WASHER_DRYER,
    }
)
DISHWASHER_TYPES: Final = frozenset(
    {DeviceType.DISHWASHER, DeviceType.DISHWASHER_SEMI_PRO, DeviceType.DISHWASHER_PRO}
)
OVEN_TYPES: Final = frozenset(
    {
        DeviceType.OVEN,
        DeviceType.OVEN_MICROWAVE,
        DeviceType.STEAM_OVEN,
        DeviceType.MICROWAVE,
        DeviceType.STEAM_OVEN_COMBI,
        DeviceType.STEAM_OVEN_MICRO,
        DeviceType.DIALOG_OVEN,
        DeviceType.STEAM_OVEN_MK2,
        DeviceType.DISH_WARMER,
    }
)
HOB_TYPES: Final = frozenset(
    {DeviceType.HOB_HIGHLIGHT, DeviceType.HOB_INDUCTION, DeviceType.HOB_INDUCT_EXTR}
)
FRIDGE_TYPES: Final = frozenset({DeviceType.FRIDGE, DeviceType.FRIDGE_FREEZER})
FREEZER_TYPES: Final = frozenset(
    {DeviceType.FREEZER, DeviceType.FRIDGE_FREEZER, DeviceType.WINE_CABINET_FREEZER}
)
WINE_TYPES: Final = frozenset(
    {
        DeviceType.WINE_CABINET,
        DeviceType.WINE_CONDITIONING_UNIT,
        DeviceType.WINE_STORAGE_CONDITIONING_UNIT,
        DeviceType.WINE_CABINET_FREEZER,
    }
)
COOLING_TYPES: Final = FRIDGE_TYPES | FREEZER_TYPES | WINE_TYPES
# Appliances that run "programs" with a duration
PROGRAM_TYPES: Final = (
    LAUNDRY_TYPES
    | DISHWASHER_TYPES
    | OVEN_TYPES
    | {DeviceType.COFFEE_SYSTEM, DeviceType.ROBOT_VACUUM_CLEANER}
)
# Appliances that report eco feedback (energy/water consumption)
ECO_TYPES: Final = LAUNDRY_TYPES | DISHWASHER_TYPES

# Event types fired on the bus and by the event entities
EVENT_PROGRAM_STARTED: Final = "program_started"
EVENT_PROGRAM_FINISHED: Final = "program_finished"
EVENT_PROGRAM_ABORTED: Final = "program_aborted"
EVENT_PROGRAM_PAUSED: Final = "program_paused"
EVENT_PROGRAM_RESUMED: Final = "program_resumed"
EVENT_FAILURE: Final = "failure"
EVENT_INFO: Final = "info"
EVENT_DOOR_OPENED: Final = "door_opened"
EVENT_DOOR_CLOSED: Final = "door_closed"
EVENT_TYPES: Final = [
    EVENT_PROGRAM_STARTED,
    EVENT_PROGRAM_FINISHED,
    EVENT_PROGRAM_ABORTED,
    EVENT_PROGRAM_PAUSED,
    EVENT_PROGRAM_RESUMED,
    EVENT_FAILURE,
    EVENT_INFO,
    EVENT_DOOR_OPENED,
    EVENT_DOOR_CLOSED,
]

# Fridge/freezer modes ("modes" action)
MODE_KEYS: Final[dict[int, str]] = {
    0: "normal",
    1: "sabbath",
    2: "party",
    3: "holiday",
}

SERVICE_START_PROGRAM: Final = "start_program"
SERVICE_SET_START_TIME: Final = "set_start_time"
SERVICE_SEND_ACTION: Final = "send_action"
SERVICE_REFRESH: Final = "refresh"
SERVICE_GET_PROGRAMS: Final = "get_programs"
