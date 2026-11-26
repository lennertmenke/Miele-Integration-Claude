"""Tests for the API client against a real local HTTP server."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from custom_components.miele_plus.api import MieleApi, MieleAuthError, MieleConnectionError


@pytest.fixture
def tokens() -> list[bool]:
    return []


def _api(session: aiohttp.ClientSession, server: TestServer, tokens: list[bool]) -> MieleApi:
    async def getter(force: bool) -> str:
        tokens.append(force)
        return "fresh" if force else "old"

    return MieleApi(session, getter, "de", base_url=str(server.make_url("")))


async def test_stream_events_and_watchdog(socket_enabled: None, tokens: list[bool]) -> None:
    async def events(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        if mode["v"] == "silent":
            await asyncio.sleep(5)
            return resp
        await resp.write(b"event: ping\ndata: ping\n\nevent: dev")
        await resp.write('ices\ndata: {"1": {"ident": {"deviceName": "Kü'.encode())
        await resp.write(b'che"}}}\n\n')
        return resp

    app = web.Application()
    mode = {"v": "normal"}
    app.router.add_get("/devices/all/events", events)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        api = _api(session, server, tokens)
        received: list = []
        connected: list = []
        await api.listen_events(
            lambda e, p: received.append((e, p)), watchdog=2, on_connect=lambda: connected.append(1)
        )
        assert connected == [1]
        assert received == [("ping", None), ("devices", {"1": {"ident": {"deviceName": "Küche"}}})]

        mode["v"] = "silent"
        with pytest.raises(MieleConnectionError):
            await api.listen_events(lambda e, p: None, watchdog=0.3)


async def test_request_retry_and_token_refresh(socket_enabled: None, tokens: list[bool]) -> None:
    calls: list[str] = []

    async def devices(request: web.Request) -> web.Response:
        calls.append(request.headers["Authorization"])
        assert request.query["language"] == "de"
        if len(calls) == 1:
            return web.Response(status=503)
        if request.headers["Authorization"] == "Bearer old" and len(calls) == 2:
            return web.Response(status=401)
        return web.json_response({"1": {}})

    async def actions(request: web.Request) -> web.Response:
        return web.json_response({"message": "Not allowed"}, status=400)

    async def denied(request: web.Request) -> web.Response:
        return web.Response(status=401)

    app = web.Application()
    app.router.add_get("/devices", devices)
    app.router.add_put("/devices/1/actions", actions)
    app.router.add_get("/devices/2/actions", denied)
    with patch("custom_components.miele_plus.api._retry_delay", return_value=0):
        async with TestServer(app) as server, aiohttp.ClientSession() as session:
            api = _api(session, server, tokens)
            assert await api.get_devices() == {"1": {}}
            assert True in tokens  # forced refresh after 401
            with pytest.raises(Exception, match="Not allowed"):
                await api.send_action("1", {"processAction": 1})
            with pytest.raises(MieleAuthError):
                await api.get_actions("2")
