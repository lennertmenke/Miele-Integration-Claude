"""Tests for the HA-independent API helpers."""

from custom_components.miele_plus.api import SSEParser
from custom_components.miele_plus.models import MieleDevice

from .conftest import WASHER


def test_sse_parser_handles_split_chunks() -> None:
    parser = SSEParser()
    payload = 'event: devices\ndata: {"a": 1}\n\nevent: ping\ndata: ping\n\n'
    events = []
    for i in range(0, len(payload), 3):
        events.extend(parser.feed(payload[i : i + 3]))
    assert events == [("devices", '{"a": 1}'), ("ping", "ping")]


def test_sse_parser_crlf_comments_and_long_lines() -> None:
    parser = SSEParser()
    big = "x" * 500_000
    events = parser.feed(f": comment\r\nevent: actions\r\ndata: {big}\r\n\r\n")
    assert events == [("actions", big)]


def test_device_model() -> None:
    dev = MieleDevice("1", WASHER)
    assert dev.status_key == "running"
    assert dev.remaining_minutes == 90
    assert dev.elapsed_minutes == 30
    assert dev.progress == 25
    assert dev.target_temperature(0) == 40
    assert dev.temperature(0) is None
    assert dev.energy_forecast == 30
    assert dev.spin_speed == 1400
    assert dev.name == "Waschmaschine"
