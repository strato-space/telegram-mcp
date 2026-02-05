# Repository Guidelines

## Project Structure & Module Organization
- `main.py` defines the core MCP tools and Telegram client wiring.
- `voice.py` is an alternate entrypoint that loads additional tooling such as exports.
- `export.py` hosts the `export_messages` tool registered via `voice.py`.
- `session_string_generator.py` handles session string creation.

## Build, Test, and Development Commands
- Install dependencies: `uv sync`
- Run the server: `uv run python main.py`
- There are no automated tests in this repo.

## Versioning
- Bump the version in `pyproject.toml` on every change.
- Keep `uv.lock` in sync with `pyproject.toml`.
