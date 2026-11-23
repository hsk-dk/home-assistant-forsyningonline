"""Client flow test against a fake portal (no Home Assistant needed).

The fake portal behaves like the real one: page requests fail with HTTP 500
unless the session has picked its location first.
"""

import asyncio
import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

import pytest

# The fake portal listens on localhost; Home Assistant's test plugin (when
# installed) blocks sockets unless a test asks for them.
pytestmark = pytest.mark.usefixtures("socket_enabled")

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web  # noqa: E402

_DIR = Path(__file__).parent.parent / "custom_components" / "forsyningonline"
_pkg = types.ModuleType("fo_pkg")
_pkg.__path__ = [str(_DIR)]
sys.modules["fo_pkg"] = _pkg
api = importlib.import_module("fo_pkg.api")


def _fake_portal(calls):
    state = {"location_set": False, "tokens": 0}

    async def token(request):
        body = await request.json()
        calls.append("token")
        if body.get("password") != "good":
            return web.Response(status=401, text="nope")
        state["tokens"] += 1
        state["location_set"] = False  # a new login is a new session
        return web.json_response({"token": f"t{state['tokens']}", "role": "User"})

    def _authed(request):
        return request.headers.get("Authorization") == f"Bearer t{state['tokens']}"

    async def current(request):
        calls.append("current")
        if not _authed(request):
            return web.json_response({"message": "UNAUTHORIZED"}, status=401)
        return web.json_response({"sessionId": "s"})

    async def loc_all(request):
        calls.append("loc_all")
        return web.json_response([{"locationGuid": "L1", "relationId": "R1"}])

    async def loc_set(request):
        calls.append("loc_set")
        body = await request.json()
        assert body == {"locationGuid": "L1", "relationId": "R1"}
        state["location_set"] = True
        return web.Response(status=200)

    async def page(request):
        calls.append("page")
        if not _authed(request):
            return web.json_response({"message": "UNAUTHORIZED"}, status=401)
        if not state["location_set"]:
            return web.Response(status=500, text="boom")
        if state.get("empty"):
            return web.json_response({"elementType": 9, "sections": []})
        body = await request.json()
        assert body["option"]["form"]["selectedDate"] == "22-11-2026"
        assert body["option"]["form"]["selectedViewscope"] == "hour"
        return web.json_response(
            {
                "elementType": 9,
                "sections": [
                    {
                        "elementType": 8,
                        "content": [
                            {
                                "elementType": 6,
                                "data": [{"name": "12:00", "value": 0.026}],
                            }
                        ],
                    }
                ],
            }
        )

    app = web.Application()
    app.router.add_post("/api/auth/token", token)
    app.router.add_get("/api/user/current", current)
    app.router.add_get("/api/Location/all", loc_all)
    app.router.add_post("/api/relay/Location/set", loc_set)
    app.router.add_post("/api/relay/page", page)
    return app, state


def _sync(coro):
    """Run a coroutine on a private loop.

    ``asyncio.run`` would reset the thread's current loop, which Home
    Assistant's test plugin (when installed) expects to be set.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _run(password, scenario):
    calls = []
    app, state = _fake_portal(calls)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    api.API_BASE_URL = f"http://127.0.0.1:{port}/api"
    try:
        async with aiohttp.ClientSession() as session:
            client = api.ForsyningOnlineClient(session, "6449-1", password)
            return await scenario(client, state), calls
    finally:
        await runner.cleanup()


def test_login_selects_location_then_reads_page():
    async def scenario(client, state):
        return await client.async_get_day(date(2026, 11, 22))

    hours, calls = _sync(_run("good", scenario))
    assert hours == {12: pytest.approx(0.026)}
    assert calls == ["token", "current", "loc_all", "loc_set", "page"]


def test_bad_password_is_auth_error():
    async def scenario(client, state):
        with pytest.raises(api.ForsyningOnlineAuthError):
            await client.async_login()

    _sync(_run("bad", scenario))


def test_expired_token_logs_in_again():
    async def scenario(client, state):
        await client.async_get_day(date(2026, 11, 22))
        state["tokens"] += 1  # server forgets the client's token
        return await client.async_get_day(date(2026, 11, 22))

    hours, calls = _sync(_run("good", scenario))
    assert hours == {12: pytest.approx(0.026)}
    assert calls.count("token") == 2 and calls.count("loc_set") == 2


def test_expired_token_is_renewed_before_the_request(monkeypatch):
    """A token past its lifetime is replaced up front, not after a 401."""
    now = [1000.0]
    monkeypatch.setattr(api, "_monotonic", lambda: now[0])

    async def scenario(client, state):
        await client.async_get_day(date(2026, 11, 22))
        now[0] += 15 * 60
        return await client.async_get_day(date(2026, 11, 22))

    hours, calls = _sync(_run("good", scenario))
    assert hours == {12: pytest.approx(0.026)}
    assert calls == [
        "token", "current", "loc_all", "loc_set", "page",
        "token", "current", "loc_all", "loc_set", "page",
    ]  # no refused "page" call in between


def test_fresh_token_is_reused(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(api, "_monotonic", lambda: now[0])

    async def scenario(client, state):
        await client.async_get_day(date(2026, 11, 22))
        now[0] += 5 * 60
        return await client.async_get_day(date(2026, 11, 22))

    _, calls = _sync(_run("good", scenario))
    assert calls.count("token") == 1 and calls.count("page") == 2


def test_day_without_hourly_data_is_no_data_error():
    async def scenario(client, state):
        state["empty"] = True
        with pytest.raises(api.ForsyningOnlineNoDataError):
            await client.async_get_day(date(2026, 11, 22))

    _sync(_run("good", scenario))
