"""Async client for the Miele 3rd-party cloud API.

This module deliberately has no Home Assistant dependency so it can be tested
in isolation. Authentication is delegated to a token callback so the
integration can plug in Home Assistant's OAuth2 session (including forced
refreshes after an unexpected 401).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
import random
from typing import Any

import aiohttp

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)

TokenGetter = Callable[[bool], Awaitable[str]]
EventCallback = Callable[[str, Any], None]

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=15)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class MieleApiError(Exception):
    """Generic API error."""


class MieleAuthError(MieleApiError):
    """Authentication failed and could not be recovered."""


class MieleConnectionError(MieleApiError):
    """Network level problem / cloud unreachable."""


class MieleRequestError(MieleApiError):
    """The API rejected a request (4xx other than auth)."""

    def __init__(self, status: int, message: str) -> None:
        """Initialize."""
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class SSEParser:
    """Incremental parser for text/event-stream payloads.

    Works on arbitrary chunk boundaries and supports arbitrarily long lines,
    which avoids aiohttp's readline size limit for large device payloads.
    """

    def __init__(self) -> None:
        """Initialize."""
        self._buffer = ""
        self._event: str | None = None
        self._data: list[str] = []

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """Feed a chunk and return all completed (event, data) tuples."""
        self._buffer += chunk
        events: list[tuple[str, str]] = []
        while True:
            idx = self._buffer.find("\n")
            if idx < 0:
                break
            line = self._buffer[:idx].rstrip("\r")
            self._buffer = self._buffer[idx + 1 :]
            if not line:
                if self._data or self._event:
                    events.append((self._event or "message", "\n".join(self._data)))
                self._event = None
                self._data = []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                self._event = value
            elif field == "data":
                self._data.append(value)
        return events


class MieleApi:
    """Thin, resilient wrapper around the Miele REST and SSE API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token_getter: TokenGetter,
        language: str = "en",
        base_url: str = API_BASE,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._token_getter = token_getter
        self.language = language
        self._base = base_url.rstrip("/")

    async def _headers(self, force_refresh: bool = False) -> dict[str, str]:
        token = await self._token_getter(force_refresh)
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        retries: int = 3,
    ) -> Any:
        """Perform a request with retry, backoff and a single forced token refresh."""
        url = f"{self._base}{path}"
        params = {"language": self.language}
        attempt = 0
        refreshed = False
        while True:
            attempt += 1
            try:
                headers = await self._headers()
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        if not refreshed:
                            refreshed = True
                            _LOGGER.debug("401 from Miele, forcing token refresh")
                            await self._token_getter(True)
                            attempt -= 1
                            continue
                        raise MieleAuthError("Access token rejected")
                    if resp.status in RETRY_STATUSES and attempt <= retries:
                        delay = _retry_delay(attempt, resp.headers.get("Retry-After"))
                        _LOGGER.debug(
                            "Miele returned %s for %s %s, retrying in %.1fs",
                            resp.status,
                            method,
                            path,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        message = _extract_message(text)
                        if resp.status >= 500 or resp.status == 429:
                            raise MieleConnectionError(f"HTTP {resp.status}: {message}")
                        raise MieleRequestError(resp.status, message)
                    if resp.status == 204:
                        return None
                    text = await resp.text()
                    if not text.strip():
                        return None
                    try:
                        return json.loads(text)
                    except ValueError as err:
                        raise MieleApiError(f"Invalid JSON from Miele: {err}") from err
            except (TimeoutError, aiohttp.ClientError) as err:
                if isinstance(err, aiohttp.ClientResponseError) and err.status in (
                    400,
                    401,
                    403,
                ):
                    # Raised by the token refresh -> refresh token invalid
                    raise MieleAuthError(str(err)) from err
                if attempt <= retries:
                    delay = _retry_delay(attempt, None)
                    _LOGGER.debug(
                        "Connection error for %s %s (%s), retrying in %.1fs",
                        method,
                        path,
                        err,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise MieleConnectionError(str(err) or type(err).__name__) from err

    # ---------------------------------------------------------------- REST

    async def get_devices(self) -> dict[str, Any]:
        """Return all appliances keyed by serial number."""
        data = await self.request("GET", "/devices")
        return data if isinstance(data, dict) else {}

    async def get_actions(self, device_id: str) -> dict[str, Any]:
        """Return the currently allowed actions for an appliance."""
        data = await self.request("GET", f"/devices/{device_id}/actions")
        return data if isinstance(data, dict) else {}

    async def get_filling_levels(self) -> dict[str, dict[str, Any]]:
        """Return consumable filling levels (TwinDos, salt, ...) keyed by serial."""
        data = await self.request("GET", "/devices/fillingLevels", retries=1)
        result: dict[str, dict[str, Any]] = {}
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and isinstance(item.get("fillingLevels"), dict):
                    result[str(item.get("deviceId"))] = item["fillingLevels"]
        elif isinstance(data, dict):
            result = {k: v for k, v in data.items() if isinstance(v, dict)}
        return result

    async def get_programs(self, device_id: str) -> list[dict[str, Any]]:
        """Return the programs that can be started remotely."""
        data = await self.request("GET", f"/devices/{device_id}/programs", retries=1)
        return data if isinstance(data, list) else []

    async def send_action(self, device_id: str, body: dict[str, Any]) -> None:
        """Send an action (processAction, light, powerOn, ...)."""
        await self.request("PUT", f"/devices/{device_id}/actions", json_body=body, retries=1)

    async def start_program(self, device_id: str, body: dict[str, Any]) -> None:
        """Select/start a program."""
        await self.request("PUT", f"/devices/{device_id}/programs", json_body=body, retries=1)

    # ----------------------------------------------------------------- SSE

    async def listen_events(
        self,
        callback: EventCallback,
        *,
        watchdog: float,
        on_connect: Callable[[], None] | None = None,
    ) -> None:
        """Connect to the event stream and dispatch events until it breaks.

        Returns normally if the server closes the stream. Raises
        ``MieleAuthError`` / ``MieleConnectionError`` on errors. The stream is
        considered dead when no data (incl. pings) arrives for ``watchdog``
        seconds.
        """
        url = f"{self._base}/devices/all/events"
        refreshed = False
        while True:
            headers = await self._headers()
            headers["Accept"] = "text/event-stream; char-set=utf-8"
            headers["Accept-Language"] = self.language
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=watchdog)
            try:
                async with self._session.get(
                    url,
                    headers=headers,
                    params={"language": self.language},
                    timeout=timeout,
                ) as resp:
                    if resp.status == 401:
                        if refreshed:
                            raise MieleAuthError("Event stream rejected token")
                        refreshed = True
                        await self._token_getter(True)
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        raise MieleConnectionError(
                            f"Event stream HTTP {resp.status}: {_extract_message(text)}"
                        )
                    if on_connect:
                        on_connect()
                    parser = SSEParser()
                    decoder = _Utf8Decoder()
                    async for chunk in resp.content.iter_any():
                        for event, data in parser.feed(decoder.decode(chunk)):
                            _dispatch(callback, event, data)
                    return
            except (TimeoutError, aiohttp.ClientError) as err:
                if isinstance(err, aiohttp.ClientResponseError) and err.status in (
                    400,
                    401,
                    403,
                ):
                    raise MieleAuthError(str(err)) from err
                raise MieleConnectionError(str(err) or type(err).__name__) from err


class _Utf8Decoder:
    """Incremental UTF-8 decoder (multi-byte chars may span chunks)."""

    def __init__(self) -> None:
        import codecs

        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def decode(self, data: bytes) -> str:
        return self._decoder.decode(data)


def _dispatch(callback: EventCallback, event: str, data: str) -> None:
    if event == "ping":
        callback("ping", None)
        return
    try:
        payload = json.loads(data) if data else None
    except ValueError:
        _LOGGER.debug("Ignoring non-JSON SSE payload for event %s", event)
        return
    try:
        callback(event, payload)
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Error handling Miele event %s", event)


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), 120.0)
        except ValueError:
            pass
    return min(2 ** (attempt - 1), 30) + random.uniform(0, 1)


def _extract_message(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        return text[:200]
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error_description") or data)[:200]
    return str(data)[:200]
