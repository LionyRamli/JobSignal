# JobSignal

[![tests](https://github.com/LionyRamli/JobSignal/actions/workflows/test.yml/badge.svg)](https://github.com/LionyRamli/JobSignal/actions/workflows/test.yml)

Predictive business intelligence from job-market data. Companies reveal expansion plans
through hiring before they announce them; JobSignal turns scattered ATS (Applicant Tracking
System) postings into evidence-based signals of expansion, investment priorities, and
emerging B2B opportunities.

## Pipeline

1. **Extraction** - scrapers for public ATS job-board APIs (Greenhouse, Lever, Workday)
2. **Harmonization** - NLP classification of job roles and locations
3. **Signals** - detection of localized hiring anomalies
4. **Delivery** - FastAPI + Streamlit alerting dashboard

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync                      # install exact locked dependencies
uv run pre-commit install    # secret scan (gitleaks) before every commit
cp .env.example .env         # optional: override settings
uv run alembic upgrade head  # create/migrate the local SQLite database
uv run pytest                # run the test suite
uv run ruff check . && uv run ruff format --check .
```

## Project layout

```
src/jobsignal/   config, logger, models, extraction/, harmonization/, signals/, storage/, api/
alembic/         database migrations (generated from storage/schema.py)
dashboard/       Streamlit app (talks to the API only)
scripts/         command-line entry points
tests/           unit/ and integration/ tests; fixtures/ holds recorded ATS responses
```

## Configuration

Settings load from `JOBSIGNAL_*` environment variables or a local `.env` file:

| Variable | Default | Purpose |
|----------|---------|---------|
| `JOBSIGNAL_DATABASE_URL` | `sqlite:///jobsignal.db` | SQLAlchemy URL (PostgreSQL in production) |
| `JOBSIGNAL_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
