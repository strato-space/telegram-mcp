# Repository Guidelines

## Project Structure & Module Organization
- `main.py` defines the core MCP tools and Telegram client wiring.
- `voice.py` is a voice-focused entrypoint; it imports `main.py` and optional tool modules (for example `export.py`).
- `export.py` hosts the `export_messages` tool and write-to-markdown logic (TOON output under `./output/`).

## Build, Test, and Development Commands
- Install dependencies: `uv sync`
- Run the read-only server: `uv run python voice.py`
- There are no automated tests in this repo.

## Versioning
- Bump the version in `pyproject.toml` on every change.
- Keep `uv.lock` in sync with `pyproject.toml`.
