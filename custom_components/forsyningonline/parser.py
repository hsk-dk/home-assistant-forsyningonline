"""Parse the hourly consumption out of a Forsyning Online page response.

The portal answers with a server-driven UI description. The hourly values are
in a chart element (``elementType`` 6) whose ``data`` is a list of
``{"name": "HH:MM", "value": 0.002}`` items. This module is deliberately free
of Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

import json
import re
from typing import Any

_HOUR_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


class ParseError(Exception):
    """The response did not contain hourly data in the expected shape."""


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("\xa0", "").replace(" ", "")
        if not text:
            return None
        # Danish formatting: "1.234,567" or "0,026"
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _iter_chart_data(node: Any):
    """Yield every ``data`` list found on a chart element, at any depth."""
    if isinstance(node, dict):
        data = node.get("data")
        if node.get("elementType") == 6 and isinstance(data, list):
            yield data
        for child in node.values():
            yield from _iter_chart_data(child)
    elif isinstance(node, list):
        for child in node:
            yield from _iter_chart_data(child)


def parse_hourly_series(payload: str | dict | list) -> list[tuple[int, float]]:
    """Return ``[(hour, cubic_metres), ...]`` in the order the portal gave them.

    The order matters on the day clocks go back: the repeated hour appears
    twice and the second one is the hour after the change.

    Raises ParseError when no hourly chart is present.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as err:
            raise ParseError(f"Response is not JSON: {err}") from err

    for data in _iter_chart_data(payload):
        series: list[tuple[int, float]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            match = _HOUR_RE.match(str(item.get("name", "")).strip())
            value = _to_float(item.get("value"))
            if match is None or value is None:
                continue
            hour = int(match.group(1))
            if 0 <= hour <= 23:
                series.append((hour, value))
        if series:
            return series

    raise ParseError("No hourly chart data found in response")


def parse_hourly(payload: str | dict | list) -> dict[int, float]:
    """Return ``{hour: cubic_metres}`` for the day in the response.

    Raises ParseError when no hourly chart is present.
    """
    return dict(parse_hourly_series(payload))
