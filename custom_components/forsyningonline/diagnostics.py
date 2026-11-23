"""Diagnostics for Forsyning Online (credentials are redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import ForsyningOnlineConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ForsyningOnlineConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "title": "**REDACTED**",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "statistic_id": coordinator.statistic_id,
            "cost_statistic_id": coordinator.cost_statistic_id,
        },
        "data": None
        if data is None
        else {
            "today": data.today,
            "yesterday": data.yesterday,
            "last_hour": data.last_hour,
            "last_hour_start": data.last_hour_start.isoformat()
            if data.last_hour_start
            else None,
            "year_total": data.year_total,
        },
    }
