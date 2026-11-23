"""Forsyning Online: water usage from a Danish waterworks customer portal."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import ForsyningOnlineClient
from .const import (
    ATTR_DAYS,
    CONF_PAGE_ID,
    DEFAULT_PAGE_ID,
    DOMAIN,
    MAX_HISTORY_DAYS,
    SERVICE_IMPORT_HISTORY,
)
from .coordinator import ForsyningOnlineCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ForsyningOnlineConfigEntry = ConfigEntry[ForsyningOnlineCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the history import action."""

    async def _import_history(call: ServiceCall) -> None:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError("Forsyning Online is not set up")
        for entry in entries:
            try:
                await entry.runtime_data.async_import_history(call.data[ATTR_DAYS])
            except UpdateFailed as err:
                raise HomeAssistantError(f"History import failed: {err}") from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_HISTORY,
        _import_history,
        schema=vol.Schema(
            {vol.Required(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_HISTORY_DAYS))}
        ),
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ForsyningOnlineConfigEntry
) -> bool:
    """Set up from a config entry."""
    # Own session, so the portal's cookies are not shared with other integrations.
    session = async_create_clientsession(hass)
    client = ForsyningOnlineClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        page_id=entry.options.get(CONF_PAGE_ID) or DEFAULT_PAGE_ID,
    )
    coordinator = ForsyningOnlineCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ForsyningOnlineConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: ForsyningOnlineConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
