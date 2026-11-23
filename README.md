# Forsyning Online for Home Assistant

Henter dit vandforbrug **time for time** fra kundeportalen på
[forsyningonline.dk](https://forsyningonline.dk) (bruges af en række danske
vandværker) og gør det tilgængeligt i Home Assistant.

> **Uofficiel.** Integrationen bruger det samme interne API som portalens egen
> hjemmeside. Det er ikke dokumenteret, og det kan ændre sig uden varsel.
> Projektet har ingen tilknytning til Forsyning Online eller dit vandværk.

*An unofficial Home Assistant integration that reads hourly water usage from
the forsyningonline.dk customer portal.*

## Hvad får du

- **Langtidsstatistik** `forsyningonline:water_total` (m³, kumulativ) med
  timeopløsning. Den kan vælges direkte som vandkilde i **Indstillinger →
  Dashboards → Energi → Vandforbrug**.
- Sensorer: **Vandforbrug i dag**, **i går** og **seneste time** (m³).
- Historik hentes ved første opsætning (som standard 30 dage).

## Installation

### Home Assistant 2026.11 eller nyere (Marketplace)

Fra 2026.11 er HACS indbygget som **Marketplace**.

1. Åbn **Indstillinger → Marketplace**. Første gang skal du acceptere
   risikoadvarslen.
2. Vælg **Tilføj fra link**, og indtast
   `https://github.com/hsk-dk/home-assistant-forsyningonline`.
3. Vælg **Forsyning Online**, installér, og genstart Home Assistant.
4. **Indstillinger → Enheder & tjenester → Tilføj integration → Forsyning
   Online**.

### Ældre versioner (HACS)

1. Åbn **HACS → ⋮ → Brugerdefinerede repositories**.
2. Tilføj `https://github.com/hsk-dk/home-assistant-forsyningonline`, kategori
   **Integration**.
3. Find **Forsyning Online** i HACS, vælg **Download**, og genstart Home
   Assistant.
4. **Indstillinger → Enheder & tjenester → Tilføj integration → Forsyning
   Online**.

### Manuelt

Kopiér mappen `custom_components/forsyningonline` til
`<config>/custom_components/` og genstart Home Assistant.

## Opsætning

Brug det **brugernavn og den adgangskode**, du logger ind med på
forsyningonline.dk. MitID virker ikke, da Home Assistant skal kunne logge ind
igen af sig selv.

Under integrationens **Indstillinger** kan du ændre opdateringsintervallet
(standard 60 min, mindst 15 min). Vær venlig mod portalen: timedata skifter
kun én gang i timen.

## Sådan virker det

Portalens token er kun gyldigt i ca. 15 minutter, så integrationen logger ind
ved hver opdatering. Den læser timeforbruget for i går og i dag, regner en
løbende sum og skriver den som ekstern statistik. Fremtidige timer springes
over. Ved nedetid hentes de manglende dage ved næste opdatering.

## Kendte begrænsninger

- Kun den samlede måler (`Totalt forbrug`) bruges.
- Skiftedage mellem sommer- og vintertid er ikke testet.
- Hvis portalen ændrer sit side-id, kan det rettes under Indstillinger.

## Udvikling

```
pip install pytest aiohttp
pytest
```

`aiohttp` skal være installeret. Ellers springer pytest `tests/test_client.py`
over uden fejl, og kun parser-testene kører. `test_client.py` bruger en falsk
portal, der håndhæver login-rækkefølgen nedenfor.

### Teknisk baggrund

Portalens API er reverse-engineeret og ikke dokumenteret.

- Base: `https://api-forsyningonline.azurewebsites.net/api`
- Rækkefølgen er tvunget, ellers svarer serveren HTTP 500:
  1. `POST /auth/token` (brugernavn/kode) giver et Bearer JWT, gyldigt i 15
     min. 400/401/403 betyder forkert login.
  2. `GET /user/current`
  3. `GET /Location/all`
  4. `POST /relay/Location/set` med første lokations `locationGuid` og
     `relationId`
  5. Side-kald (server-drevet UI-JSON, standard page id står i `const.py`).
- Timedata ligger i et chart-element (`elementType == 6`). Navnene er
  `"HH:MM"`, og værdier kan have dansk decimalkomma (`"0,026"`). Parsing er i
  `parser.py`, som ikke importerer noget fra Home Assistant.
- `api.py` logger kun status og højst 200 tegn fejltekst, aldrig request-body.
  Ved 401/403 logges der ind igen én gang.

Statistikken skrives med `async_add_external_statistics` som
`forsyningonline:water_total` (kumulativ `sum`). Første kørsel henter hele
backfill-perioden (standard 30 dage, højst 365). Forkert login giver
`ConfigEntryAuthFailed` og dermed reauth, andre fejl giver `UpdateFailed`.

## Udgivelser

Release-noter samles automatisk af Release Drafter ud fra merged pull requests.
PR'er får labels (`feature`, `fix`, `chore`, `docs` …) automatisk ud fra titel og
branch-navn, og labels bestemmer også versionsforslaget. Brug `skip-changelog`
for at holde en PR ude af noterne.

Ny version:

1. Gå til **Actions → Create Release → Run workflow**.
2. Skriv versionen (fx `0.1.3`). Egne noter og pre-release er valgfrit.

Workflowet kører testene, sætter versionen i `manifest.json`, committer den til
`main`, opretter tagget `vX.Y.Z` og udgiver releasen med `forsyningonline.zip`.
Noterne kommer fra egne noter, ellers Release Drafters udkast, ellers
autogenererede noter. HACS/Marketplace bruger tagget som versionsnummer.

## Licens

MIT
