"""Data coordinator: fetches hourly usage and imports it as statistics."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ForsyningOnlineAuthError,
    ForsyningOnlineClient,
    ForsyningOnlineError,
    ForsyningOnlineNoDataError,
)
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_PRICE,
    CONF_UPDATE_INTERVAL,
    COST_STATISTIC_ID_SUFFIX,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_PRICE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_BACKFILL_DAYS,
    MIN_UPDATE_INTERVAL,
    STATISTIC_ID_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)

# Statistics are written in pieces of this many days, so a failure halfway
# through a long backfill keeps what was already fetched.
CHUNK_DAYS = 7
# How far back to look for the cumulative sum an import continues from.
SUM_LOOKBACK = timedelta(days=30)


@dataclass
class UsageData:
    """What the sensors show."""

    today: float | None
    yesterday: float | None
    last_hour: float | None
    last_hour_start: datetime | None
    year_total: float | None = None


def _local_hour_to_utc(
    day: date, hour: int, fold: int, tz: tzinfo
) -> datetime | None:
    """UTC start of a local clock hour, or None if that hour does not exist.

    ``fold`` is 1 for the second pass through a repeated hour (clocks going
    back). An hour skipped when clocks go forward has no UTC start.
    """
    local = datetime.combine(day, time(hour), tzinfo=tz).replace(fold=fold)
    utc = dt_util.as_utc(local)
    back = utc.astimezone(tz)
    if back.date() != day or back.hour != hour:
        return None
    return utc


def _hour_deltas(
    days: list[date],
    per_day: dict[date, list[tuple[int, float]]],
    tz: tzinfo,
    now_utc: datetime,
) -> list[tuple[datetime, float]]:
    """Ordered ``(utc_hour_start, cubic_metres)``, future hours left out."""
    deltas: dict[datetime, float] = {}
    for day in days:
        seen: dict[int, int] = {}
        for hour, value in per_day.get(day, []):
            fold = seen.get(hour, 0)
            seen[hour] = fold + 1
            if fold > 1:
                continue
            start = _local_hour_to_utc(day, hour, fold, tz)
            if start is None or start > now_utc:
                continue
            deltas[start] = value
    return sorted(deltas.items())


def _metadata(
    name: str,
    statistic_id: str,
    unit: str = UnitOfVolume.CUBIC_METERS,
    unit_class: str | None = "volume",
) -> StatisticMetaData:
    """Build metadata that works across Home Assistant versions."""
    meta: dict = {
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": unit,
    }
    annotations = getattr(StatisticMetaData, "__annotations__", {})
    if "mean_type" in annotations:
        try:
            from homeassistant.components.recorder.models import (  # noqa: PLC0415
                StatisticMeanType,
            )

            meta["mean_type"] = StatisticMeanType.NONE
        except ImportError:  # pragma: no cover
            meta["has_mean"] = False
    if "has_mean" in annotations and "mean_type" not in meta:
        meta["has_mean"] = False
    if "unit_class" in annotations:
        meta["unit_class"] = unit_class
    return StatisticMetaData(**meta)  # type: ignore[typeddict-item]


class ForsyningOnlineCoordinator(DataUpdateCoordinator[UsageData]):
    """Polls the portal and keeps the long-term statistics up to date."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ForsyningOnlineClient,
    ) -> None:
        interval = max(
            MIN_UPDATE_INTERVAL,
            int(entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)),
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )
        self._client = client
        self._entry = entry
        self.statistic_id = f"{DOMAIN}:{STATISTIC_ID_SUFFIX}"
        self.cost_statistic_id = f"{DOMAIN}:{COST_STATISTIC_ID_SUFFIX}"

    # -- statistics helpers -------------------------------------------------

    async def _last_imported_hour(
        self, statistic_id: str | None = None
    ) -> datetime | None:
        statistic_id = statistic_id or self.statistic_id
        result = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            statistic_id,
            True,
            {"sum"},
        )
        rows = result.get(statistic_id)
        if not rows:
            return None
        start = rows[0]["start"]
        if isinstance(start, (int, float)):
            return dt_util.utc_from_timestamp(start)
        return dt_util.as_utc(start)

    async def _sum_before(
        self, first_hour: datetime, statistic_id: str | None = None
    ) -> float:
        """Cumulative sum just before ``first_hour`` (0 if nothing earlier).

        Looks back over SUM_LOOKBACK rather than a single hour: if the hour
        right before happens to be missing, starting from 0 would make the
        cumulative sum jump back to zero.
        """
        statistic_id = statistic_id or self.statistic_id
        result = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            first_hour - SUM_LOOKBACK,
            first_hour,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        rows = result.get(statistic_id) or []
        for row in reversed(rows):
            if row.get("sum") is not None:
                return float(row["sum"])
        return 0.0

    def _price(self) -> float:
        try:
            return max(0.0, float(self._entry.options.get(CONF_PRICE, DEFAULT_PRICE)))
        except (TypeError, ValueError):
            return 0.0

    def _cost_metadata(self) -> StatisticMetaData:
        return _metadata(
            "Forsyning Online water cost",
            self.cost_statistic_id,
            unit=self.hass.config.currency,
            unit_class=None,
        )

    async def _backfill_cost(self, price: float) -> None:
        """First time a price is set: price the usage already imported."""
        if await self._last_imported_hour(self.cost_statistic_id) is not None:
            return
        result = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            datetime(2000, 1, 1, tzinfo=dt_util.UTC),
            None,
            {self.statistic_id},
            "hour",
            None,
            {"sum"},
        )
        previous = 0.0
        cost = 0.0
        stats: list[StatisticData] = []
        for row in result.get(self.statistic_id) or []:
            total = row.get("sum")
            if total is None:
                continue
            start = row["start"]
            start = (
                dt_util.utc_from_timestamp(start)
                if isinstance(start, (int, float))
                else dt_util.as_utc(start)
            )
            cost += max(0.0, float(total) - previous) * price
            previous = float(total)
            stats.append(StatisticData(start=start, state=cost, sum=cost))
        if stats:
            async_add_external_statistics(self.hass, self._cost_metadata(), stats)

    # -- main update --------------------------------------------------------

    async def _async_update_data(self) -> UsageData:
        tz = dt_util.get_default_time_zone()
        today = dt_util.now().date()
        yesterday = today - timedelta(days=1)

        price = self._price()
        if price > 0:
            await self._backfill_cost(price)

        last_hour_imported = await self._last_imported_hour()
        if last_hour_imported is None:
            backfill = min(
                int(self._entry.data.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS)),
                MAX_BACKFILL_DAYS,
            )
            start_day = today - timedelta(days=max(backfill, 1))
        else:
            start_day = min(
                dt_util.as_local(last_hour_imported).date() - timedelta(days=1),
                yesterday,
            )

        days = [start_day + timedelta(days=i) for i in range((today - start_day).days + 1)]
        per_day: dict[date, list[tuple[int, float]]] = {}
        running: float | None = None
        cost_running: float | None = None
        latest: tuple[datetime, float] | None = None

        try:
            for i in range(0, len(days), CHUNK_DAYS):
                chunk = days[i : i + CHUNK_DAYS]
                for day in chunk:
                    try:
                        per_day[day] = await self._client.async_get_day_series(day)
                    except ForsyningOnlineNoDataError as err:
                        # Normal just after midnight, or before the meter existed.
                        _LOGGER.debug("No hourly data for %s: %s", day, err)
                    if len(days) > 3 and day != today:
                        await asyncio.sleep(0.3)  # gentle during backfill

                ordered = _hour_deltas(chunk, per_day, tz, dt_util.utcnow())
                if not ordered:
                    continue
                if running is None:
                    running = await self._sum_before(ordered[0][0])
                stats: list[StatisticData] = []
                for start, value in ordered:
                    running += value
                    stats.append(StatisticData(start=start, state=running, sum=running))
                async_add_external_statistics(
                    self.hass,
                    _metadata("Forsyning Online water usage", self.statistic_id),
                    stats,
                )
                if price > 0:
                    if cost_running is None:
                        cost_running = await self._sum_before(
                            ordered[0][0], self.cost_statistic_id
                        )
                    cost_stats: list[StatisticData] = []
                    for start, value in ordered:
                        cost_running += value * price
                        cost_stats.append(
                            StatisticData(
                                start=start, state=cost_running, sum=cost_running
                            )
                        )
                    async_add_external_statistics(
                        self.hass, self._cost_metadata(), cost_stats
                    )
                latest = ordered[-1]
        except ForsyningOnlineAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ForsyningOnlineError as err:
            raise UpdateFailed(str(err)) from err

        if not per_day:
            # Not one day had data: more likely a changed portal than a quiet night.
            raise UpdateFailed("The portal returned no hourly data")

        def day_total(d: date) -> float | None:
            hours = per_day.get(d)
            return round(sum(v for _, v in hours), 3) if hours else None

        # Year to date comes from the portal's own yearly view. A failure here
        # must not break the hourly import, so it only leaves the sensor empty.
        year_total: float | None = None
        try:
            years = await self._client.async_get_years(today.year)
            value = years.get(today.year)
            year_total = round(value, 3) if value is not None else None
        except ForsyningOnlineAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ForsyningOnlineError as err:
            _LOGGER.debug("Could not fetch yearly usage: %s", err)

        return UsageData(
            year_total=year_total,
            today=day_total(today),
            yesterday=day_total(yesterday),
            last_hour=latest[1] if latest else None,
            last_hour_start=latest[0] if latest else None,
        )
