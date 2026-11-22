"""Forsyning Online: water usage from a Danish waterworks customer portal."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ForsyningOnlineClient
from .const import CONF_PAGE_ID, DEFAULT_PAGE_ID
from .coordinator import ForsyningOnlineCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ForsyningOnlineConfigEntry = ConfigEntry[ForsyningOnlineCoordinator]


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
