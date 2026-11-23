# Forsyning Online – Home Assistant integration

- Repository content (README, code, comments, workflows) is in English. The UI is localised in English and Danish (`translations/`).
- Reply to Henrik in Danish.
- Read the README: it covers usage, technical background (the portal's API) and the release process.
- Test: `pip install -r requirements_test.txt && pytest -q` (without the requirements the tests that need them are skipped, so a low count is not a pass).
- Releases are made via Actions → Create Release. Do not create tags yourself.
