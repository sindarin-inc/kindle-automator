# Repository Guidelines

## Project Structure & Modules
- `server/`: Flask REST API (entrypoint: `server/server.py`).
- `views/`: App state machine, UI navigation, and view utilities.
- `handlers/`: Actions for specific app states.
- `database/`: SQLAlchemy models, Alembic migrations, and connection helpers.
- `scripts/`: Operational scripts (DB, VNC table, migrations).
- `tests/`: Pytest suite for API, concurrency, and state logic.
- `logs/`, `screenshots/`, `covers/`, `apks/`: Runtime artifacts and assets.

## Build, Run, and Test
- Init env: `make init` (create uv venv + install deps) or `make deps` (install deps).
- Start server (preferred): `make claude-run` (background; safe restarts, logs to `logs/server_output.log`).
- Start server (foreground): `make server`.
- Emulator workflows: `make dev` (emulator+server), `make run-emulator`, `make run-emulator-choose`, `make register-avd`.
- Tests: `make test` (use `.env`, auto-detected). Generate tokens first: `make test-staff-auth` and `make test-web-auth` then set in `.env`.
- Lint/format: `make lint` (isort, black, flake8). Always run before PRs.

## Coding Style & Naming
- Python, 4‑space indent, max line length 110 (Black).
- Imports: sorted by isort (`--profile black`); keep at file top.
- Naming: `snake_case` for functions/vars, `PascalCase` for classes, `snake_case.py` for modules.
- Linting: flake8 (strict errors `E9,F63,F7,F82`). Keep code DRY; comment only for non‑obvious context.

## Testing Guidelines
- Framework: pytest. Markers: `expensive` (deselect via `-m "not expensive"`).
- Layout: tests live in `tests/`, files named `test_*.py`, functions `test_*`.
- Run examples: `uv run dotenv run pytest -q`, or single file: `pytest tests/test_multi_user.py -k scenario`.
- Integration tests require tokens in `.env` (`INTEGRATION_TEST_STAFF_AUTH_TOKEN`, `WEB_INTEGRATION_TEST_AUTH_TOKEN`).

## Commit & PR Guidelines
- Commits: concise, imperative present (e.g., "Add profile switch logging"). Group related changes.
- PRs: include summary, rationale, linked issue (e.g., `KINDLE-AUTOMATOR-123`), test plan, and logs/screenshots if UI/state changes.
- Checks: run `make lint` and `make test`; avoid adding new tests unless requested.

## Security & Config
- Secrets live in `.env`; copy from `.env.example`. Never commit secrets.
- Env auto-detect: `.env`/`.env.staging`/`.env.prod` used by `dotenv` in Makefiles.
- Prefer `make claude-run` or `/shutdown` API over killing processes manually.
- For Apple Silicon devs using Android Studio AVDs: register via `make android-studio-avd`, start emulator in Studio, then `make server`.

