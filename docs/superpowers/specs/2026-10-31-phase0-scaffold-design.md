# Phase 0: Scaffold - Design (short)

**Intent:** a runnable, graded-quality empty repo so Phase 1.1 can start straight into TDD.
Solo project; deliverable is the GitHub repo link, so CI and lint cleanliness are visible quality signals.

**Goals:** approved `src/` layout; `uv` + lockfile; ruff lint/format; pytest; `config.py`;
central `logger.py`; Alembic wired to settings + `storage/schema.py`; GitHub Actions CI; git init.

**Non-goals:** any scraping/NLP/API logic; playwright (deferred to 1.1) and spaCy (deferred to 1.3).

**Constraints:** Python 3.12.2 pinned (`>=3.12,<3.13`); Windows dev machine, Ubuntu CI.

## Approaches considered
1. **uv + pyproject + hatchling (chosen by user)** - fast, lockfile, single config file.
2. pip + venv + requirements.txt - familiar, but no lockfile and slower installs.
3. Poetry - lockfile, but slower and less common for new projects.

## Decisions (assistant's calls, flagged for review)
- `pydantic-settings` for config (validation + `.env` support) - `JOBSIGNAL_` env prefix.
- Logging configures only the `jobsignal` package logger (not root), `propagate=False`,
  idempotent; third-party library logs are not captured.
- SQLite connections enable `PRAGMA foreign_keys=ON`; Alembic uses batch mode on SQLite.
- Constraint naming convention on `Base.metadata` so migrations behave the same on SQLite and PostgreSQL.
- Assembly test: `compare_metadata` must be empty after `upgrade head` (schema.py and migrations can't drift).
- CI on push to `main` and on all PRs; read-only token; `uv sync --locked` fails if the lockfile is stale.
