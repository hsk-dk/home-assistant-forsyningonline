"""Client for the Forsyning Online customer portal."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from typing import Any

import aiohttp

from .const import API_BASE_URL, DEFAULT_METER, DEFAULT_PAGE_ID
from .parser import ParseError, parse_hourly_series, parse_yearly

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The portal's token lives for about 15 minutes. Log in a little earlier so a
# normal update does not start with a request that is bound to be refused.
_TOKEN_LIFETIME = 14 * 60


def _monotonic() -> float:
    """Clock for token expiry (a function so tests can move it)."""
    return time.monotonic()


class ForsyningOnlineError(Exception):
    """Generic communication or parsing error."""


class ForsyningOnlineAuthError(ForsyningOnlineError):
    """Login was rejected."""


class ForsyningOnlineNoDataError(ForsyningOnlineError):
    """The portal answered, but had no hourly values for that day.

    Normal right after midnight, or for days before the meter was installed.
    """


class ForsyningOnlineClient:
    """Logs in with username and password and reads hourly water usage.

    The portal hands out a JWT that is valid for roughly 15 minutes, so the
    client simply logs in again when it has no token or the token is refused.

    Like the portal's own front end, a fresh session must pick its
    consumption location (``Location/set``) before the portal will answer
    page requests; without it the server fails with HTTP 500.
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
        self._token_expires = 0.0
        self._lock = asyncio.Lock()

    # -- low level ----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        authed: bool = True,
        what: str = "request",
    ) -> tuple[int, str]:
        headers = {"Accept": "application/json, text/plain, */*"}
        if authed:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                json=body,
                headers=headers,
                timeout=_TIMEOUT,
            ) as resp:
                text = await resp.text()
                status = resp.status
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning("Forsyning Online %s: cannot reach portal: %r", what, err)
            raise ForsyningOnlineError(f"Cannot reach portal: {err}") from err

        if authed and status in (401, 403):
            # An expired token is routine; the caller logs in again.
            _LOGGER.debug("Forsyning Online %s: token refused (HTTP %s)", what, status)
        elif status != 200 and status != 204:
            # Never log the request body (it can hold the password); the
            # portal's own error text is safe and very useful.
            _LOGGER.warning(
                "Forsyning Online %s failed: HTTP %s %s", what, status, text[:200]
            )
        return status, text

    @staticmethod
    def _json(text: str, what: str) -> Any:
        try:
            return json.loads(text)
        except ValueError as err:
            raise ForsyningOnlineError(f"{what}: response is not JSON") from err

    # -- session ------------------------------------------------------------

    async def async_login(self) -> None:
        """Log in, then select the consumption location like the web app."""
        self._token = None
        status, text = await self._request(
            "POST",
            "/auth/token",
            body={"username": self._username, "password": self._password},
            authed=False,
            what="login",
        )
        if status in (400, 401, 403):
            raise ForsyningOnlineAuthError(f"Login rejected (HTTP {status})")
        if status != 200:
            raise ForsyningOnlineError(f"Login failed (HTTP {status})")

        data = self._json(text, "login")
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise ForsyningOnlineAuthError("Login response had no token")
        self._token = token
        self._token_expires = _monotonic() + _TOKEN_LIFETIME

        await self._select_location()

    async def _select_location(self) -> None:
        """Mirror the web app: user/current, Location/all, Location/set."""
        status, _ = await self._request("GET", "/user/current", what="user lookup")
        if status in (401, 403):
            raise ForsyningOnlineAuthError(f"Token refused (HTTP {status})")

        status, text = await self._request("GET", "/Location/all", what="location list")
        if status in (401, 403):
            raise ForsyningOnlineAuthError(f"Token refused (HTTP {status})")
        if status != 200:
            raise ForsyningOnlineError(f"Location list failed (HTTP {status})")
        locations = self._json(text, "location list")
        if not isinstance(locations, list) or not locations:
            raise ForsyningOnlineError("No consumption location on this account")

        # Most customers have exactly one. Take the first otherwise.
        loc = locations[0]
        status, _ = await self._request(
            "POST",
            "/relay/Location/set",
            body={
                "locationGuid": loc.get("locationGuid"),
                "relationId": loc.get("relationId"),
            },
            what="location select",
        )
        if status in (401, 403):
            raise ForsyningOnlineAuthError(f"Token refused (HTTP {status})")
        if status != 200:
            raise ForsyningOnlineError(f"Location select failed (HTTP {status})")

    # -- data ---------------------------------------------------------------

    async def _post_page(self, day: date, scope: str = "hour") -> str:
        status, text = await self._request(
            "POST",
            "/relay/page",
            body={
                "pageId": self._page_id,
                "option": {
                    "getAnswer": "YES",
                    "form": {
                        "selectedMeter": self._meter,
                        "selectedDate": day.strftime("%d-%m-%Y"),
                        "selectedViewscope": scope,
                    },
                },
            },
            what="data request",
        )
        if status in (401, 403):
            raise ForsyningOnlineAuthError(f"Token refused (HTTP {status})")
        if status != 200:
            raise ForsyningOnlineError(f"Data request failed (HTTP {status})")
        return text

    async def async_get_day_series(
        self, day: date, *, drop_placeholder: bool = True
    ) -> list[tuple[int, float]]:
        """Return ``[(hour, cubic_metres), ...]`` for one calendar day.

        Hours are local time, in the order the portal gave them. Raises
        ForsyningOnlineNoDataError when the portal has no hourly values.
        ``drop_placeholder`` is passed on to the parser.
        """
        async with self._lock:
            if self._token is None or _monotonic() >= self._token_expires:
                await self.async_login()
            try:
                text = await self._post_page(day)
            except ForsyningOnlineAuthError:
                # Token refused anyway: log in once more, then try again.
                await self.async_login()
                text = await self._post_page(day)

        try:
            return parse_hourly_series(text, drop_placeholder=drop_placeholder)
        except ParseError as err:
            raise ForsyningOnlineNoDataError(str(err)) from err

    async def async_get_day(self, day: date) -> dict[int, float]:
        """Return ``{hour: cubic_metres}`` for one calendar day (local time)."""
        return dict(await self.async_get_day_series(day))

    async def async_get_years(self, first_year: int) -> dict[int, float]:
        """Return ``{year: cubic_metres}`` from the portal's yearly view."""
        async with self._lock:
            if self._token is None or _monotonic() >= self._token_expires:
                await self.async_login()
            try:
                text = await self._post_page(date(first_year, 1, 1), "year")
            except ForsyningOnlineAuthError:
                await self.async_login()
                text = await self._post_page(date(first_year, 1, 1), "year")

        try:
            return parse_yearly(text)
        except ParseError as err:
            raise ForsyningOnlineNoDataError(str(err)) from err
