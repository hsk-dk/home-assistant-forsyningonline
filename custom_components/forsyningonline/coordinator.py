"""Data coordinator: fetches hourly usage and imports it as statistics."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

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
)
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_BACKFILL_DAYS,
    MIN_UPDATE_INTERVAL,
    STATISTIC_ID_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class UsageData:
    """What the sensors show."""

    today: float | None
    yesterday: float | None
    last_hour: float | None
    last_hour_start: datetime | None


def _metadata(name: str, statistic_id: str) -> StatisticMetaData:
    """Build metadata that works across Home Assistant versions."""
    meta: dict = {
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
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
        meta["unit_class"] = "volume"
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

    # -- statistics helpers -------------------------------------------------

    async def _last_imported_hour(self) -> datetime | None:
        result = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            self.statistic_id,
            True,
            {"sum"},
        )
        rows = result.get(self.statistic_id)
        if not rows:
            return None
        start = rows[0]["start"]
        if isinstance(start, (int, float)):
            return dt_util.utc_from_timestamp(start)
        return dt_util.as_utc(start)

    async def _sum_before(self, first_hour: datetime) -> float:
        """Cumulative sum at the hour just before ``first_hour`` (0 if none)."""
        prev = first_hour - timedelta(hours=1)
        result = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            prev,
            first_hour,
            {self.statistic_id},
            "hour",
            None,
            {"sum"},
        )
        rows = result.get(self.statistic_id) or []
        for row in reversed(rows):
            if row.get("sum") is not None:
                return float(row["sum"])
        return 0.0

    # -- main update --------------------------------------------------------

    async def _async_update_data(self) -> UsageData:
        tz = dt_util.get_default_time_zone()
        now_local = dt_util.now()
        today = now_local.date()
        yesterday = today - timedelta(days=1)

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

        per_day: dict[date, dict[int, float]] = {}
        day = start_day
        try:
            while day <= today:
                per_day[day] = await self._client.async_get_day(day)
                day += timedelta(days=1)
                if day <= today and len(per_day) > 3:
                    await asyncio.sleep(0.3)  # gentle during backfill
        except ForsyningOnlineAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ForsyningOnlineError as err:
            raise UpdateFailed(str(err)) from err

        # Flatten to ordered (utc_hour_start, delta) pairs, skipping the future.
        now_utc = dt_util.utcnow()
        deltas: dict[datetime, float] = {}
        for d, hours in per_day.items():
            for hour, value in hours.items():
                local = datetime.combine(d, time(hour), tzinfo=tz)
                start = dt_util.as_utc(local)
                if start > now_utc:
                    continue
                deltas[start] = value
        ordered = sorted(deltas.items())

        if ordered:
            running = await self._sum_before(ordered[0][0])
            stats: list[StatisticData] = []
            for start, value in ordered:
                running += value
                stats.append(StatisticData(start=start, state=running, sum=running))
            async_add_external_statistics(
                self.hass,
                _metadata("Forsyning Online – vandforbrug", self.statistic_id),
                stats,
            )

        # Values for the sensors.
        def day_total(d: date) -> float | None:
            hours = per_day.get(d)
            return round(sum(hours.values()), 3) if hours else None

        last_hour_start: datetime | None = None
        last_hour_value: float | None = None
        if ordered:
            last_hour_start, last_hour_value = ordered[-1]

        return UsageData(
            today=day_total(today),
            yesterday=day_total(yesterday),
            last_hour=last_hour_value,
            last_hour_start=last_hour_start,
        )
