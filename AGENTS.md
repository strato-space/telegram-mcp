# Repository Guidelines

## Project Structure & Module Organization
- `main.py` defines the core MCP tools and Telegram client wiring.
- `main.py` auto-loads optional tool modules (for example `export.py`) so `export_messages` is available when running `main.py`.
- `voice.py` is an alternate entrypoint that can load additional tooling such as exports.
- `export.py` hosts the `export_messages` tool and write-to-markdown logic (TOON output under `./output/`).
- `session_string_generator.py` handles session string creation.

## Build, Test, and Development Commands
- Install dependencies: `uv sync`
- Run the server: `uv run python main.py`
- There are no automated tests in this repo.

## Versioning
- Bump the version in `pyproject.toml` on every change.
- Keep `uv.lock` in sync with `pyproject.toml`.
