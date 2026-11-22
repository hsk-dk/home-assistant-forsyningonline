"""Client for the Forsyning Online customer portal."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import aiohttp

from .const import API_BASE_URL, DEFAULT_METER, DEFAULT_PAGE_ID
from .parser import ParseError, parse_hourly

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)


class ForsyningOnlineError(Exception):
    """Generic communication or parsing error."""


class ForsyningOnlineAuthError(ForsyningOnlineError):
    """Login was rejected."""


class ForsyningOnlineClient:
    """Logs in with username and password and reads hourly water usage.

    The portal hands out a JWT that is valid for roughly 15 minutes, so the
    client simply logs in again when it has no token or the token is refused.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        page_id: str = DEFAULT_PAGE_ID,
        meter: str = DEFAULT_METER,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._page_id = page_id
        self._meter = meter
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def async_login(self) -> None:
        """Log in and keep the bearer token."""
        try:
            async with self._session.post(
                f"{API_BASE_URL}/auth/token",
                json={"username": self._username, "password": self._password},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise ForsyningOnlineAuthError(
                        f"Login rejected (HTTP {resp.status})"
                    )
                if resp.status != 200:
                    raise ForsyningOnlineError(f"Login failed (HTTP {resp.status})")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ForsyningOnlineError(f"Cannot reach portal: {err}") from err

        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise ForsyningOnlineAuthError("Login response had no token")
        self._token = token

    async def _post_page(self, day: date) -> str:
        assert self._token is not None
        body = {
            "pageId": self._page_id,
            "option": {
                "getAnswer": "YES",
                "form": {
                    "selectedMeter": self._meter,
                    "selectedDate": day.strftime("%d-%m-%Y"),
                    "selectedViewscope": "hour",
                },
            },
        }
        try:
            async with self._session.post(
                f"{API_BASE_URL}/relay/page",
                json=body,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise ForsyningOnlineAuthError(f"Token refused (HTTP {resp.status})")
                if resp.status != 200:
                    raise ForsyningOnlineError(f"Data request failed (HTTP {resp.status})")
                return await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ForsyningOnlineError(f"Cannot reach portal: {err}") from err

    async def async_get_day(self, day: date) -> dict[int, float]:
        """Return ``{hour: cubic_metres}`` for one calendar day (local time)."""
        async with self._lock:
            if self._token is None:
                await self.async_login()
            try:
                text = await self._post_page(day)
            except ForsyningOnlineAuthError:
                # Token expired: log in once more, then try again.
                await self.async_login()
                text = await self._post_page(day)

        try:
            return parse_hourly(text)
        except ParseError as err:
            raise ForsyningOnlineError(str(err)) from err
