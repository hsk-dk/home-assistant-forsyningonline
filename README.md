[![release](https://img.shields.io/github/v/release/hsk-dk/home-assistant-forsyningonline?style=plastic&labelColor=green)](https://github.com/hsk-dk/home-assistant-forsyningonline/releases) [![Buy me a coffee](https://img.shields.io/static/v1?label=Buy%20me%20a%20coffee&message=and%20say%20thanks&color=orange&logo=buymeacoffee&logoColor=white&style=plastic)](https://www.buymeacoffee.com/hskdk)

# Forsyning Online for Home Assistant

Reads your water usage **hour by hour** from the customer portal at
[forsyningonline.dk](https://forsyningonline.dk) (used by a number of Danish
waterworks) and makes it available in Home Assistant.

> **Unofficial.** The integration uses the same internal API as the portal's
> own website. It is not documented and may change without notice. The project
> is not affiliated with Forsyning Online or your waterworks.

*Dansk: Uofficiel integration der henter timeforbrug af vand fra
forsyningonline.dk. Brugergrænsefladen er oversat til dansk og engelsk.*

## What you get

- **Long-term statistics** `forsyningonline:water_total` (m³, cumulative) with
  hourly resolution. It can be picked directly as a water source under
  **Settings → Dashboards → Energy → Water consumption**.
- Sensors: **Water used today**, **yesterday**, **last hour** and **this year** (m³). The yearly figure comes from the portal's yearly view.
- History is imported during setup (30 days by default).
- Localisation in English and Danish.

## Installation

### Home Assistant 2026.11 or newer (Marketplace)

From 2026.11 HACS is built in as the **Marketplace**.

1. Open **Settings → Marketplace**. Accept the risk warning the first time.
2. Choose **Add from link** and enter
   `https://github.com/hsk-dk/home-assistant-forsyningonline`.
3. Select **Forsyning Online**, install it and restart Home Assistant.
4. **Settings → Devices & services → Add integration → Forsyning Online**.

### Older versions (HACS)

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/hsk-dk/home-assistant-forsyningonline` with category
   **Integration**.
3. Find **Forsyning Online** in HACS, choose **Download** and restart Home
   Assistant.
4. **Settings → Devices & services → Add integration → Forsyning Online**.

### Manual

Copy the folder `custom_components/forsyningonline` to
`<config>/custom_components/` and restart Home Assistant.

## Setup

Use the **username and password** you log in with on forsyningonline.dk. MitID
does not work, because Home Assistant has to be able to log in again by itself.

Under the integration's **Options** you can change the update interval
(default 60 min, minimum 15 min). Please be kind to the portal: hourly data
only changes once an hour.

Set **Price per m³ (incl. VAT)** in Options to get the statistic
`forsyningonline:water_cost` (in your Home Assistant currency). Pick it as
**Use a cost statistic** on the water source in the Energy dashboard to see
what the water costs. The price is applied to the whole history the first time
it is set; later changes only apply to newly imported hours. Fixed charges
(standing and meter fees) are not included. Leave the price at 0 to turn it off.

## How it works

The portal's token is only valid for about 15 minutes, so the integration logs
in again whenever the token has expired (in practice on every update at the
default interval). It reads the hourly usage for yesterday and today,
calculates a running sum and writes it as external statistics. Future hours are
skipped. After downtime the missing days are fetched on the next update.

## Known limitations

- Only the total meter (`Totalt forbrug`) is used.
- On the day the clocks go back the portal may list the repeated hour twice or
  once; it is handled in both cases, but the real portal's behaviour on that
  day is unverified.
- If the portal changes its page id, it can be corrected under Options.

## Development

```
pip install -r requirements_test.txt
pytest
```

The requirements include `aiohttp` and Home Assistant's test plugin
(`pytest-homeassistant-custom-component`). Without them pytest skips the
tests that need them and only the rest runs:

- `tests/test_parser.py`: parsing of the portal's responses.
- `tests/test_client.py`: login and token handling against a fake portal that
  enforces the login order below (needs `aiohttp`).
- `tests/test_coordinator.py`: the statistics import against a real recorder,
  including cumulative sums, days without data, partial backfills and daylight
  saving time (needs the Home Assistant test plugin).

### Technical background

The portal's API is reverse-engineered and undocumented.

- Base: `https://api-forsyningonline.azurewebsites.net/api`
- The order is enforced, otherwise the server answers HTTP 500:
  1. `POST /auth/token` (username/password) returns a Bearer JWT valid for 15
     minutes. 400/401/403 means wrong login.
  2. `GET /user/current`
  3. `GET /Location/all`
  4. `POST /relay/Location/set` with the first location's `locationGuid` and
     `relationId`
  5. Page calls (server-driven UI JSON, the default page id is in `const.py`).
- Hourly data lives in a chart element (`elementType == 6`). Names are
  `"HH:MM"` and values may use a Danish decimal comma (`"0,026"`). Parsing is
  in `parser.py`, which imports nothing from Home Assistant.
- `api.py` only logs the status and at most 200 characters of error text,
  never the request body. On 401/403 it logs in again once.

Statistics are written with `async_add_external_statistics` as
`forsyningonline:water_total` (cumulative `sum`). The first run fetches the
whole backfill period (default 30 days, at most 365). A wrong login raises
`ConfigEntryAuthFailed` and thereby reauth; other errors raise `UpdateFailed`.
A day without hourly data (just after midnight, or before the meter existed)
is skipped; only when no day has data does the update fail. A backfill is
written in pieces of seven days, so a failure keeps what was already fetched.

## Releases

Release notes are collected automatically by Release Drafter from merged pull
requests. PRs are labelled (`feature`, `fix`, `chore`, `docs` …) automatically
from their title and branch name, and the labels also decide the suggested
version. Use `skip-changelog` to keep a PR out of the notes.

New version:

1. Go to **Actions → Create Release → Run workflow**.
2. Enter the version (e.g. `0.1.3`). Custom notes and pre-release are optional.

The workflow runs the tests, sets the version in `manifest.json`, commits it to
`main`, creates the tag `vX.Y.Z` and publishes the release with
`forsyningonline.zip`. The notes come from custom notes, otherwise the Release
Drafter draft, otherwise auto-generated notes. HACS/Marketplace use the tag as
the version number.

## Support

If you find the integration useful, you can say thanks:

<a href="https://www.buymeacoffee.com/hskdk" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;" ></a>

## License

MIT
