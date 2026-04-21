# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI L2 service (auth, users/roles, alerts, appeals, projects), with migrations in `backend/migrations/`.
- `collector/`: data ingestion pipeline (connectors, normalization, quality checks, CLI). Runtime artifacts live in `collector/data/` and `collector/logs/` (gitignored).
- `pages/`, `scripts/`, `styles/`, `index.html`: static frontend and admin UI assets.
- `tests/`: pytest suite for authentication, RBAC, and business APIs.
- `deploy/`: systemd service units, nginx config, and environment templates.

## Build, Test, and Development Commands
```bash
pip install -r requirements.txt        # Install dependencies
python3 -m http.server 8080            # Preview static pages locally
uvicorn backend.main:app --reload      # Run FastAPI backend
python3 -m collector.cli init-db       # Initialize collector DB and source registry
python3 -m collector.cli run           # Execute one collection run
pytest -q                              # Run all tests
ruff check backend/ collector/         # Lint Python code
bash scripts/start-server.sh           # Start integrated control server + frontend
```

## Coding Style & Naming Conventions
- Python uses 4-space indentation, type hints, and `snake_case` naming; models/schemas use `PascalCase`.
- Keep API modules domain-based under `backend/routers/` and align test files with router names.
- JavaScript in `scripts/` follows `camelCase`; keep DOM IDs explicit and feature-oriented.
- Prefer small, composable functions in collector connectors and normalizers over large monolithic handlers.

## Testing Guidelines
- Test framework: `pytest` (configured in `pytest.ini` with `-ra -q --tb=short` and `tests/` as root).
- Name tests as `tests/test_<feature>.py`; share fixtures in `tests/conftest.py`.
- For API changes, add or update coverage for permission checks, failure paths, and status transitions.
- Run `pytest -q` before opening a PR; CI runs tests on Python 3.11 and 3.12.

## Commit & Pull Request Guidelines
- Follow the existing Conventional Commit pattern: `feat(scope): ...`, `fix(scope): ...`, `chore: ...` (Chinese or English summaries are both used in history).
- Keep each commit focused on one concern (backend, collector, or frontend).
- PRs should include scope, rationale, affected modules, and local verification commands/results.
- Include screenshots when changing `pages/`, `styles/`, or admin/dashboard UI behavior.
- Do not commit runtime DB files, logs, or secrets; start config from `deploy/*.env.sample`.
