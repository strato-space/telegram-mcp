# Repository Guidelines

## Project Structure & Module Organization
- `main.py` defines the core MCP tools and Telegram client wiring.
- `session_string_generator.py` handles session string creation.

## Build, Test, and Development Commands
- Install dependencies: `uv sync`
- Run the server: `uv run python main.py`
- There are no automated tests in this repo.

## Versioning
- Bump the version in `pyproject.toml` on every change.
- Keep `uv.lock` in sync with `pyproject.toml`.
