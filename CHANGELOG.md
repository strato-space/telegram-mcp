# Changelog

## 2026-02-06
### PROBLEM SOLVED
- **12:20** `export_messages` now resolves numeric chat IDs more reliably by falling back to explicit peer types and a dialog scan when the Telethon entity cache is cold.

### FEATURE IMPLEMENTED
- **12:20** `export_messages` now emits machine-readable `TOON` with per-chat metadata and a tabular `messages[]` array ordered oldest to newest.
- **12:20** Export automatically expands migrated chat families (legacy group plus migrated supergroup) and includes forum `topics[]` when available.

### CHANGES
- **12:20** Added `output/` to `.gitignore`.
- **12:20** Loaded optional tool modules (`export.py`) from `main.py` so running `main.py` directly includes `export_messages`.
- **12:20** Added `toon-format` dependency and bumped the package version to `2.1.4` (refreshed `uv.lock`).

## 2026-02-04
### PROBLEM SOLVED
- None.

### FEATURE IMPLEMENTED
- Added `export_messages` to export multiple chat histories into a markdown file with a resource link.

### CHANGES
- Moved export logic into `export.py` and registered it from `voice.py`.
- Added `export` to package modules and updated the lockfile.
- Bumped the package version to `2.1.3`.
