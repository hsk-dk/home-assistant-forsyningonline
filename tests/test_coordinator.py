"""Coordinator tests: the statistics import (needs Home Assistant's test plugin).

The portal client is replaced by a fake that serves hourly series per day.
"""

import types
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    statistics_during_period,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.forsyningonline import coordinator as coordinator_module
from custom_components.forsyningonline.api import (
    ForsyningOnlineAuthError,
    ForsyningOnlineError,
    ForsyningOnlineNoDataError,
)
from custom_components.forsyningonline.const import (
    CONF_BACKFILL_DAYS,
    DOMAIN,
)
from custom_components.forsyningonline.coordinator import (
    ForsyningOnlineCoordinator,
    _hour_deltas,
)

CPH = ZoneInfo("Europe/Copenhagen")
STATISTIC_ID = f"{DOMAIN}:water_total"


class FakeClient:
    """Serves ``{date: [(hour, m3), ...]}``; other days have no data."""

    def __init__(self, data):
        self.data = data
        self.calls = []
        self.drop_flags = {}

    async def async_get_years(self, first_year):
        return {first_year: 12.5}

    async def async_get_day_series(self, day, *, drop_placeholder=True):
        self.calls.append(day)
        self.drop_flags[day] = drop_placeholder
        value = self.data.get(day)
        if value is None:
            raise ForsyningOnlineNoDataError("no data")
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """The coordinator pauses between days during a backfill; skip that."""

    async def _sleep(_):
        return None

    monkeypatch.setattr(
        coordinator_module, "asyncio", types.SimpleNamespace(sleep=_sleep)
    )


@pytest.fixture
async def setup(recorder_mock, hass, freezer):
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    freezer.move_to("2026-11-22 12:30:00+00:00")  # 13:30 in Copenhagen (UTC+1)

    def make(data, backfill_days=2, options=None):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "u", "password": "p", CONF_BACKFILL_DAYS: backfill_days},
            options=options or {},
        )
        entry.add_to_hass(hass)
        client = FakeClient(data)
        return ForsyningOnlineCoordinator(hass, entry, client), client

    return make


async def _stat_sums(hass, statistic_id):
    await async_wait_recording_done(hass)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return {
        dt_util.utc_from_timestamp(row["start"]): row["sum"]
        for row in result.get(statistic_id, [])
    }


async def _sums(hass):
    return await _stat_sums(hass, STATISTIC_ID)


def _utc(day, hour):
    return datetime(2026, 11, day, hour, tzinfo=UTC)


DATA = {
    date(2026, 11, 20): [(23, 1.0)],
    date(2026, 11, 21): [(0, 2.0), (1, 3.0)],
    date(2026, 11, 22): [(0, 0.5), (14, 9.0)],  # 14:00 has not started yet
}


async def test_first_import_is_cumulative_and_skips_the_future(setup, hass):
    coordinator, _ = setup(DATA)
    data = await coordinator._async_update_data()

    assert await _sums(hass) == {
        _utc(20, 22): pytest.approx(1.0),
        _utc(20, 23): pytest.approx(3.0),
        _utc(21, 0): pytest.approx(6.0),
        _utc(21, 23): pytest.approx(6.5),
    }
    assert data.today == pytest.approx(9.5)
    assert data.yesterday == pytest.approx(5.0)
    assert data.last_hour == pytest.approx(0.5)  # the future hour is not "last"


async def test_next_update_continues_the_sum(setup, hass, freezer):
    coordinator, _ = setup(DATA)
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    freezer.move_to("2026-11-22 13:30:00+00:00")  # 14:00 local has now started
    await coordinator._async_update_data()

    sums = await _sums(hass)
    assert sums[_utc(21, 23)] == pytest.approx(6.5)  # re-imported, unchanged
    assert sums[_utc(22, 13)] == pytest.approx(15.5)


async def test_missing_hour_before_the_window_does_not_reset_the_sum(setup, hass, freezer
):
    coordinator, client = setup(DATA)
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    # The portal now only has the newest hour; the hour before it is missing.
    client.data = {date(2026, 11, 22): [(14, 9.0)]}
    freezer.move_to("2026-11-22 13:30:00+00:00")
    await coordinator._async_update_data()

    assert (await _sums(hass))[_utc(22, 13)] == pytest.approx(15.5)  # not 9.0


async def test_day_without_data_is_not_an_error(setup, hass):
    coordinator, _ = setup(
        {date(2026, 11, 21): [(10, 1.0), (11, 0.5)]}, backfill_days=1
    )
    data = await coordinator._async_update_data()  # today has no data yet

    assert data.today is None
    assert data.yesterday == pytest.approx(1.5)
    assert data.last_hour == pytest.approx(0.5)


async def test_no_data_at_all_fails_the_update(setup, hass):
    coordinator, _ = setup({})
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_rejected_login_starts_reauth(setup, hass):
    coordinator, _ = setup({date(2026, 11, 22): ForsyningOnlineAuthError("no")})
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_failed_chunk_keeps_the_earlier_ones(setup, hass):
    days = [date(2026, 11, d) for d in range(2, 23)]  # 21 days = 3 chunks
    data = {d: [(5, 1.0)] for d in days}
    data[date(2026, 11, 17)] = ForsyningOnlineError("boom")  # in the third chunk
    coordinator, _ = setup(data, backfill_days=20)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert len(await _sums(hass)) == 14  # the first two chunks were written


# -- daylight saving time ------------------------------------------------------


def _deltas(day, series):
    return _hour_deltas([day], {day: series}, CPH, datetime(2030, 1, 1, tzinfo=UTC))


def test_clocks_going_back_gives_two_distinct_hours():
    result = _deltas(date(2026, 10, 25), [(1, 1.0), (2, 2.0), (2, 3.0), (3, 4.0)])
    assert result == [
        (datetime(2026, 10, 24, 23, tzinfo=UTC), 1.0),
        (datetime(2026, 10, 25, 0, tzinfo=UTC), 2.0),
        (datetime(2026, 10, 25, 1, tzinfo=UTC), 3.0),
        (datetime(2026, 10, 25, 2, tzinfo=UTC), 4.0),
    ]


def test_clocks_going_forward_skips_the_missing_hour():
    result = _deltas(date(2026, 3, 29), [(1, 1.0), (2, 2.0), (3, 3.0)])
    assert result == [
        (datetime(2026, 3, 29, 0, tzinfo=UTC), 1.0),
        (datetime(2026, 3, 29, 1, tzinfo=UTC), 3.0),
    ]


def test_an_hour_listed_three_times_ignores_the_extra():
    result = _deltas(date(2026, 10, 25), [(2, 1.0), (2, 2.0), (2, 3.0)])
    assert [v for _, v in result] == [1.0, 2.0]


async def test_cost_statistic_follows_the_price(setup, hass):
    coordinator, _ = setup(DATA, options={"price_per_m3": 16.2})
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    cost_id = f"{DOMAIN}:water_cost"
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        {cost_id},
        "hour",
        None,
        {"sum"},
    )
    sums = {
        dt_util.utc_from_timestamp(row["start"]): row["sum"]
        for row in result.get(cost_id, [])
    }
    assert sums[_utc(20, 22)] == pytest.approx(1.0 * 16.2)
    assert sums[_utc(21, 23)] == pytest.approx(6.5 * 16.2)


async def test_hours_imported_without_a_price_are_priced_later(setup, hass, freezer):
    coordinator, _ = setup(DATA, options={"price_per_m3": 10})
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    # Price off while 14:00 local is imported, then on again.
    entry = coordinator._entry
    hass.config_entries.async_update_entry(entry, options={})
    freezer.move_to("2026-11-22 13:30:00+00:00")
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    hass.config_entries.async_update_entry(entry, options={"price_per_m3": 10})
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    cost_id = f"{DOMAIN}:water_cost"
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        {cost_id},
        "hour",
        None,
        {"sum"},
    )
    sums = {
        dt_util.utc_from_timestamp(row["start"]): row["sum"]
        for row in result.get(cost_id, [])
    }
    assert sums[_utc(22, 13)] == pytest.approx(15.5 * 10)


async def test_history_import_reaches_back_before_existing_data(setup, hass):
    data = dict(DATA)
    data[date(2026, 11, 18)] = [(5, 4.0)]
    coordinator, _ = setup(data, backfill_days=1)
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    await coordinator.async_import_history(5)

    sums = await _sums(hass)
    assert sums[_utc(18, 4)] == pytest.approx(4.0)  # the new, older start
    assert sums[_utc(20, 22)] == pytest.approx(5.0)
    assert sums[_utc(21, 23)] == pytest.approx(10.5)  # whole range re-based


async def test_price_set_on_existing_history_keeps_the_cost_sum_continuous(
    setup, hass, monkeypatch
):
    """Turning the price on later must not restart the cost sum in the window.

    The cost of the old hours is queued first; the import of the newest days
    must continue from that, not from what the database holds at that moment.
    Whether the recorder has committed by then is a matter of timing, so the
    test holds all writes back until the import is done, which is the worst case.
    """
    full = {date(2026, 11, d): [(h, 0.1) for h in range(24)] for d in (19, 20, 21)}
    full[date(2026, 11, 22)] = [(h, 0.1) for h in range(13)]
    coordinator, _ = setup(full, backfill_days=3)
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    held = []
    real_add = coordinator_module.async_add_external_statistics
    monkeypatch.setattr(
        coordinator_module,
        "async_add_external_statistics",
        lambda hass_, meta, stats: held.append((meta, stats)),
    )
    hass.config_entries.async_update_entry(
        coordinator._entry, options={"price_per_m3": 10}
    )
    await coordinator._async_update_data()
    for meta, stats in held:
        real_add(hass, meta, stats)

    water = await _stat_sums(hass, STATISTIC_ID)
    cost = await _stat_sums(hass, f"{DOMAIN}:water_cost")
    assert cost.keys() == water.keys()
    ordered = [cost[k] for k in sorted(cost)]
    assert ordered == sorted(ordered), "the cost sum must never go down"
    last = max(water)
    assert cost[last] == pytest.approx(water[last] * 10)


async def test_only_old_days_get_the_manual_reading_filter(setup, hass):
    """Recent days are live data; a big 00:00 value there is real usage."""
    coordinator, client = setup({date(2026, 11, 21): [(5, 1.0)]}, backfill_days=5)
    await coordinator._async_update_data()

    # Today is 22 November: only days before the 19th may be filtered.
    assert client.drop_flags[date(2026, 11, 17)] is True
    assert client.drop_flags[date(2026, 11, 18)] is True
    assert client.drop_flags[date(2026, 11, 19)] is False
    assert client.drop_flags[date(2026, 11, 22)] is False
