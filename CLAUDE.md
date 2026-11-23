# Forsyning Online – Home Assistant-integration

Custom integration der henter timeforbrug af vand fra forsyningonline.dk (ejer: Henrik, Grejs Vandværk, Vejle) og lægger det ind som langtidsstatistik i Home Assistant. Henrik skriver dansk. README og UI-tekster er på dansk.

## Status
- Version 0.1.2, udgivet via workflowet Create Release (release + `forsyningonline.zip`).
- Kører hos Henrik på HA 2026.11 (installeret via Marketplace, tidligere HACS). Entry loaded, sensorer viser data, Energi-dashboardet bruger `forsyningonline:water_total` ("Grejs Vand").
- 9 tests (pytest) i CLAUDE.md-optælling; lokalt sås 6 bestået og 1 sprunget over (ikke undersøgt). Workflows: `validate.yml` (tests, hassfest, hacs), `release-drafter.yml` og `create-release.yml`.
- Validate er grøn. HACS-tjekket krævede About-beskrivelse og topics (sat af Henrik) og `categories` i manifestet (`water.meters_leak_detection`).

## Portalens API (reverse-engineeret)
- Base: `https://api-forsyningonline.azurewebsites.net/api`
- Rækkefølge er tvunget, ellers svarer serveren HTTP 500:
  1. `POST /auth/token` (brugernavn/kode) giver Bearer JWT, gyldig 15 min. 400/401/403 = forkert login.
  2. `GET /user/current`
  3. `GET /Location/all`
  4. `POST /relay/Location/set` med første lokations `locationGuid` + `relationId`
  5. Side-kald (server-drevet UI-JSON, standard page id i `const.py`).
- Timedata ligger i et chart-element (`elementType == 6`). Navne er `"HH:MM"`, værdier kan have dansk decimalkomma (`"0,026"`). Parsing er i `parser.py` (ingen HA-imports).
- `api.py` logger kun status og højst 200 tegn fejltekst, aldrig request-body. Ved 401/403 logges der ind igen én gang.

## Arkitektur
- `coordinator.py`: henter i går + i dag (første kørsel: hele backfill-perioden, default 30 dage, max 365). Opdateringsinterval default 60 min, minimum 15.
- Statistik skrives med `async_add_external_statistics`, id `forsyningonline:water_total`, kumulativ `sum`. Basis findes via `statistics_during_period` og `get_last_statistics`. Fremtidige timer springes over. `StatisticMetaData` bygges kompatibelt på tværs af HA-versioner (`mean_type`, `unit_class="volume"`).
- Auth-fejl giver `ConfigEntryAuthFailed` (reauth), andre fejl `UpdateFailed`.
- `sensor.py`: tre vandsensorer (i dag, i går, sidste time).

## Test og udgivelse
- `pip install pytest aiohttp && pytest -q`
- `tests/test_client.py` bruger en falsk aiohttp-portal der håndhæver login-rækkefølgen ovenfor.
- Ny version: Henrik kører Actions → Create Release (workflow_dispatch) med versionsnummer. Workflowet tester, bumper `manifest.json`, committer til main, tagger `vX.Y.Z` og udgiver release + `forsyningonline.zip`. Noter: egne > Release Drafter-udkast (`.github/release-drafter.yml`) > autogenererede. Agenten behøver ikke selv tagge.
- Marketplace/HACS kræver offentligt repo, `hacs.json` i roden og GitHub-releases.

## Kendte begrænsninger i agent-miljøet
- Tag-push gennem git-proxyen fejler. Lad Henrik oprette tags/releases i GitHub-UI.
- Fejl-logs fra Actions kræver login og kan ikke hentes uden.
