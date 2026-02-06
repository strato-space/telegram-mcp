# Changelog

## 2026-02-06
### PROBLEM SOLVED
- **12:20** `export_messages` now resolves numeric chat IDs more reliably by falling back to explicit peer types and a dialog scan when the Telethon entity cache is cold.

### FEATURE IMPLEMENTED
- **12:20** `export_messages` now exports chat history as `TOON` (chat metadata plus tabular `messages[]`, oldest to newest; includes migrated supergroups when available).

### CHANGES
- **12:20** Added `output/` to `.gitignore`.
- **12:20** Loaded optional tool modules (`export.py`) from `main.py` so running `main.py` directly includes `export_messages`.
- **12:20** Added `toon-format` dependency and bumped the package version to `2.0.8` (refreshed `uv.lock`).

## 2026-02-05
### PROBLEM SOLVED
- **03:16** Removed unused imports after extracting export functionality to keep the server clean.

### FEATURE IMPLEMENTED
- **03:22** Added the `voice.py` entrypoint and `export.py` tool module for markdown exports.

### CHANGES
- **03:16** Bumped the package version to `2.0.5`.
- **03:16** Updated the MCP dependency to `>=1.25.0` and refreshed `uv.lock`.
- **03:16** Documented the MCP SDK requirement in `README.md`.
- **03:22** Copied `voice.py` and `export.py` from the read-only server.
- **03:22** Added setuptools module metadata and bumped the version to `2.0.6`.
