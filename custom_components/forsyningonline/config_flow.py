"""Config flow for Forsyning Online."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    ForsyningOnlineAuthError,
    ForsyningOnlineClient,
    ForsyningOnlineError,
)
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_PAGE_ID,
    CONF_PRICE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_PAGE_ID,
    DEFAULT_PRICE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_BACKFILL_DAYS,
    MIN_UPDATE_INTERVAL,
)


class ForsyningOnlineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup."""

    VERSION = 1

    async def _validate(self, username: str, password: str) -> str | None:
        """Return an error key, or None when the login works."""
        client = ForsyningOnlineClient(
            async_create_clientsession(self.hass), username, password
        )
        try:
            await client.async_login()
        except ForsyningOnlineAuthError:
            return "invalid_auth"
        except ForsyningOnlineError:
            return "cannot_connect"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            error = await self._validate(username, user_input[CONF_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title=f"Forsyning Online ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_BACKFILL_DAYS: user_input[CONF_BACKFILL_DAYS],
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(
                        CONF_BACKFILL_DAYS, default=DEFAULT_BACKFILL_DAYS
                    ): vol.All(int, vol.Range(min=1, max=MAX_BACKFILL_DAYS)),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            error = await self._validate(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ForsyningOnlineOptionsFlow()


class ForsyningOnlineOptionsFlow(OptionsFlow):
    """Polling interval and page id."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                    ): vol.All(int, vol.Range(min=MIN_UPDATE_INTERVAL, max=1440)),
                    vol.Optional(
                        CONF_PRICE,
                        default=options.get(CONF_PRICE, DEFAULT_PRICE),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                    vol.Required(
                        CONF_PAGE_ID,
                        default=options.get(CONF_PAGE_ID, DEFAULT_PAGE_ID),
                    ): str,
                }
            ),
        )
