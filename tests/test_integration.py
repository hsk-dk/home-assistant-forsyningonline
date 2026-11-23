"""Whole-integration tests: setup, config flow, options, reauth, action, diagnostics.

The portal client is replaced by a fake. Needs Home Assistant's test plugin.
"""

import types
from datetime import date

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

import custom_components.forsyningonline as integration
import custom_components.forsyningonline.config_flow as config_flow
from custom_components.forsyningonline import coordinator as coordinator_module
from custom_components.forsyningonline.api import (
    ForsyningOnlineAuthError,
    ForsyningOnlineError,
    ForsyningOnlineNoDataError,
)
from custom_components.forsyningonline.const import DOMAIN
from custom_components.forsyningonline.diagnostics import (
    async_get_config_entry_diagnostics,
)

DATA = {
    date(2026, 11, 20): [(h, 0.1) for h in range(24)],
    date(2026, 11, 21): [(h, 0.1) for h in range(24)],
    date(2026, 11, 22): [(h, 0.1) for h in range(13)],
}


class FakeClient:
    """Stands in for ForsyningOnlineClient."""

    last = None

    def __init__(self, session, username, password, **kwargs):
        self.username = username
        self.password = password
        self.fail_auth = False
        FakeClient.last = self

    async def async_login(self):
        if self.password == "bad":
            raise ForsyningOnlineAuthError("wrong password")
        if self.username == "down":
            raise ForsyningOnlineError("cannot reach")

    async def async_get_day_series(self, day, *, drop_placeholder=True):
        if self.fail_auth:
            raise ForsyningOnlineAuthError("rejected")
        if day not in DATA:
            raise ForsyningOnlineNoDataError("no data")
        return DATA[day]

    async def async_get_years(self, first_year):
        return {first_year: 123.456}


@pytest.fixture(autouse=True)
def fake_portal(monkeypatch):
    async def _sleep(_):
        return None

    monkeypatch.setattr(
        coordinator_module, "asyncio", types.SimpleNamespace(sleep=_sleep)
    )
    monkeypatch.setattr(integration, "ForsyningOnlineClient", FakeClient)
    monkeypatch.setattr(config_flow, "ForsyningOnlineClient", FakeClient)


@pytest.fixture
async def env(recorder_mock, enable_custom_integrations, hass, freezer):
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    await hass.config.async_update(currency="DKK")
    freezer.move_to("2026-11-22 12:30:00+00:00")
    return hass


async def _add_entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="u",
        data={"username": "u", "password": "secret", "backfill_days": 2},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_the_sensors_and_unloads(env):
    entry = await _add_entry(env)
    assert entry.state is ConfigEntryState.LOADED

    states = {s.entity_id: s.state for s in env.states.async_all("sensor")}
    assert states == {
        "sensor.forsyning_online_water_used_today": "1.3",
        "sensor.forsyning_online_water_used_yesterday": "2.4",
        "sensor.forsyning_online_water_used_this_year": "123.456",
        "sensor.forsyning_online_water_used_last_hour": "0.1",
    }

    assert await env.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_config_flow_creates_an_entry_and_refuses_the_same_account_twice(env):
    result = await env.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await env.config_entries.flow.async_configure(
        result["flow_id"], {"username": "Bob", "password": "p", "backfill_days": 5}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["username"] == "Bob"

    again = await env.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    again = await env.config_entries.flow.async_configure(
        again["flow_id"], {"username": "bob", "password": "x", "backfill_days": 5}
    )
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("username", "password", "error"),
    [("u", "bad", "invalid_auth"), ("down", "p", "cannot_connect")],
)
async def test_config_flow_shows_login_errors(env, username, password, error):
    result = await env.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await env.config_entries.flow.async_configure(
        result["flow_id"],
        {"username": username, "password": password, "backfill_days": 5},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_a_rejected_login_starts_reauth_and_a_new_password_fixes_it(env):
    entry = await _add_entry(env)
    FakeClient.last.fail_auth = True
    await entry.runtime_data.async_refresh()
    await env.async_block_till_done()

    flows = [
        f for f in env.config_entries.flow.async_progress()
        if f["context"].get("source") == SOURCE_REAUTH
    ]
    assert len(flows) == 1

    result = await env.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"password": "new-secret"}
    )
    await env.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-secret"


async def test_options_flow_saves_the_price_and_reloads(env):
    entry = await _add_entry(env)
    result = await env.config_entries.options.async_init(entry.entry_id)
    result = await env.config_entries.options.async_configure(
        result["flow_id"],
        {"update_interval_minutes": 30, "price_per_m3": 16.2, "page_id": "page"},
    )
    await env.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["price_per_m3"] == 16.2
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_interval.total_seconds() == 30 * 60


async def test_import_history_action_fetches_the_range(env):
    entry = await _add_entry(env)
    FakeClient.last.fail_auth = False
    await env.services.async_call(DOMAIN, "import_history", {"days": 3}, blocking=True)
    await async_wait_recording_done(env)
    assert entry.runtime_data.data.today == pytest.approx(1.3)


async def test_import_history_action_refuses_nonsense_days(env):
    await _add_entry(env)
    with pytest.raises(vol.Invalid):
        await env.services.async_call(
            DOMAIN, "import_history", {"days": 0}, blocking=True
        )


async def test_diagnostics_redact_the_login(env):
    entry = await _add_entry(env)
    diagnostics = await async_get_config_entry_diagnostics(env, entry)
    text = str(diagnostics)
    assert "secret" not in text
    assert diagnostics["entry"]["data"]["username"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["data"]["today"] == pytest.approx(1.3)
