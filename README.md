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
uv run python scripts/run_scrape.py anthropic databricks stripe  # scrape + store
uv run python scripts/run_harmonize.py                          # role + location taxonomy
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

## Storage

| Table | Holds |
|-------|-------|
| `companies` | one row per (ATS source, board token) |
| `scrape_runs` | each CLI run: `running` → `succeeded` / `partial` / `failed` |
| `snapshots` | one fetch of one company in one run: `ok` / `partial` / `failed` |
| `postings` | latest state of each posting + `first_seen_at` / `last_seen_at` / `closed_at` |
| `snapshot_postings` | which postings were open in each snapshot (the time series) |

A posting is closed only when a **complete** fetch no longer lists it; failed or partial
fetches never close anything. Run one scrape at a time per database.

## Harmonization

`harmonize` classifies every stored posting whose taxonomy version is missing or outdated. Results
are deterministic, with spaCy phrase rules and a gazetteer kept in `src/jobsignal/harmonization/data/`.

| Dimension | Values |
|-----------|--------|
| Role family (16) | software_engineering, ml_research, data, solutions_engineering, security, product_management, program_management, design, sales, customer_success, marketing, operations, finance, legal, people, other |
| Seniority (7) | intern, entry, mid, senior, staff_plus, manager, director_plus (no signal → mid) |
| Location | `kind\|country\|region\|city` with ISO 3166 codes; kinds city / region / country / remote; a posting can have many |

Accuracy is gated in CI on hand-labelled real data. Titles score ≥90% on family and seniority, and
locations score ≥95%. A 25% holdout split is reported separately.
Unresolvable places are reported and never guessed. Editing a rule file requires bumping
`TAXONOMY_VERSION`, and CI enforces this. A bumped version reprocesses every posting.

## Configuration

Settings load from `JOBSIGNAL_*` environment variables or a local `.env` file:

| Variable | Default | Purpose |
|----------|---------|---------|
| `JOBSIGNAL_DATABASE_URL` | `sqlite:///jobsignal.db` | SQLAlchemy URL (PostgreSQL in production) |
| `JOBSIGNAL_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
