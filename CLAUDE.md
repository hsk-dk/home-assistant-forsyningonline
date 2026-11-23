# Forsyning Online – Home Assistant integration

- Repository content (README, code, comments, workflows) is in English. The UI is localised in English and Danish (`translations/`).
- Reply to Henrik in Danish.
- Read the README: it covers usage, technical background (the portal's API) and the release process.
- Test: `pip install pytest aiohttp && pytest -q` (without `aiohttp` the client tests are skipped).
- Releases are made via Actions → Create Release. Do not create tags yourself.
