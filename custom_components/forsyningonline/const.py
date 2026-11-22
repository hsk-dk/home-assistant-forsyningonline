"""Constants for the Forsyning Online integration."""

from __future__ import annotations

DOMAIN = "forsyningonline"

API_BASE_URL = "https://api-forsyningonline.azurewebsites.net/api"

# Id of the "Vandforbrug" page in the Forsyning Online portal. It is read from
# the portal's own front end and can be overridden in the integration options
# if the portal ever changes it.
DEFAULT_PAGE_ID = "67b625b2-5a0c-47a7-8c25-90ef1599ccc0"
DEFAULT_METER = "total"

CONF_BACKFILL_DAYS = "backfill_days"
CONF_PAGE_ID = "page_id"
CONF_UPDATE_INTERVAL = "update_interval_minutes"

DEFAULT_BACKFILL_DAYS = 30
MAX_BACKFILL_DAYS = 365
DEFAULT_UPDATE_INTERVAL = 60  # minutes
MIN_UPDATE_INTERVAL = 15  # be gentle with a small waterworks' portal

STATISTIC_ID_SUFFIX = "water_total"
