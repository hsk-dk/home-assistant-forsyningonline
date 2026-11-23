"""Tests for the response parser (no Home Assistant needed)."""

import importlib.util
import json
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "forsyningonline"
    / "parser.py"
)
_spec = importlib.util.spec_from_file_location("fo_parser", _PATH)
parser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parser)

# Same shape as the portal's real answer for view scope "hour": a page with
# a filter section and a section holding a chart element (elementType 6).
HOURS = [0.002, 0.009, 0, 0.001, 0, 0.002, 0, 0.006, 0, 0.002, 0.001, 0,
         0.026, 0, 0.007, 0.002, 0, 0, 0, 0, 0, 0, 0, 0]


def _response(values=HOURS):
    return json.dumps(
        {
            "elementType": 9,
            "title": "Vandforbrug",
            "sections": [
                {"elementType": 8, "header": "Afgrænsning af visning", "content": []},
                {
                    "elementType": 8,
                    "header": "Forbrug for perioden: 22.11.26",
                    "content": [
                        {
                            "elementType": 6,
                            "chartType": 3,
                            "data": [
                                {"name": f"{h:02d}:00", "value": v}
                                for h, v in enumerate(values)
                            ],
                        }
                    ],
                },
            ],
        }
    )


def test_parses_24_hours():
    hours = parser.parse_hourly(_response())
    assert len(hours) == 24
    assert hours[12] == pytest.approx(0.026)
    assert sum(hours.values()) == pytest.approx(sum(HOURS))


def test_danish_decimal_strings():
    payload = {
        "elementType": 6,
        "data": [
            {"name": "12:00", "value": "0,026"},
            {"name": "13:00", "value": "1.234,5"},
        ],
    }
    hours = parser.parse_hourly(payload)
    assert hours == {12: pytest.approx(0.026), 13: pytest.approx(1234.5)}


def test_partial_day_is_fine():
    hours = parser.parse_hourly(_response(HOURS[:6]))
    assert sorted(hours) == [0, 1, 2, 3, 4, 5]


def test_ignores_non_hour_labels_and_other_charts():
    # A year/month/day chart must not be mistaken for hourly data.
    payload = {
        "sections": [
            {"elementType": 6, "data": [{"name": "Jan", "value": 3}]},
            {"elementType": 6, "data": [{"name": "05:00", "value": 0.5}]},
        ]
    }
    assert parser.parse_hourly(payload) == {5: 0.5}


def test_not_json():
    with pytest.raises(parser.ParseError):
        parser.parse_hourly("<html>nope</html>")


def test_no_chart():
    with pytest.raises(parser.ParseError):
        parser.parse_hourly({"elementType": 9, "sections": []})


def test_series_keeps_order_and_repeated_hours():
    """The day clocks go back, the portal may list 02:00 twice."""
    payload = {
        "elementType": 6,
        "data": [
            {"name": "01:00", "value": 1},
            {"name": "02:00", "value": 2},
            {"name": "02:00", "value": 3},
            {"name": "03:00", "value": 4},
        ],
    }
    assert parser.parse_hourly_series(payload) == [(1, 1.0), (2, 2.0), (2, 3.0), (3, 4.0)]


def test_chart_without_hours_is_a_parse_error():
    with pytest.raises(parser.ParseError):
        parser.parse_hourly({"elementType": 6, "data": []})
