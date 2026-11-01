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
uv run python scripts/run_detect.py                             # hiring signals
uv run python scripts/run_api.py                                # read-only API on 127.0.0.1:8000
uv run python scripts/run_dashboard.py                          # dashboard on 127.0.0.1:8501
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

## Signals

`detect` scores hiring per company x role family x country. It works at four levels
(company, +family, +country, +both) and stores an append-only run with its parameters, the
taxonomy version and the raw z, observed and baseline values of every row.

| Detector | Basis | Question | Signal |
|----------|-------|----------|--------|
| `volume` | new openings **we observed** each week | Is this week unusual for this cell? | z ≥ 3 with ≥ 5 openings (expansion); z ≤ −3 with baseline ≥ 5 (contraction) |
| `mix_shift` *(provisional)* | ATS `first_published` dates | Did this cell's share of the company's openings jump (last 4 vs previous 12 weeks)? | expansions only by default (z ≥ 3, ≥ 5 openings) |

**How `volume` scores a week**
- The week is compared with the previous 8 *measurable* weeks:
  `z = (x − μ) / sqrt(max(s², μ, 1))`. The Poisson floor stops sparse cells from producing
  infinite scores, so a cell whose baseline is below 9 a week cannot signal a contraction.
- A week is measurable only when scraping covered it continuously. Every gap between
  successful scrapes that touches the week must be no longer than max(48 h, 1.5 × that
  company's usual gap).
- So an outage hides its week **and** the backlog week after it. Weeks with a board re-import
  (many ids replaced at once) or a collapsed board are hidden too. The first scrape's week
  never counts.

**Honest limits**
- **Cold start.** `volume` needs ≥ 8 measurable weeks after the first scrape, so schedule a
  daily scrape. Until then it reports `insufficient_history`.
- **`mix_shift` is survivorship-biased.** It only sees postings that are still open. In
  simulation, fast-filling roles showed an "expansion" in about half of runs with no real
  change. Treat it as a lead to investigate, not evidence. Its contractions are not flagged
  (`mix_flag_contractions=False`).
- **False positives.** With only 8 baseline weeks and bursty posting, simulated false-positive
  rates are about 0.2–1 % (Poisson) to 3–4 % (overdispersed) per cell-week, against a nominal
  0.13 %. That means roughly 1–15 false `notable` expansions per run. Recalibrate the
  threshold once real history exists.
- **Overlapping levels.** One event can appear at up to four levels; the dashboard should
  group them.
- **Drill-down.** `jobsignal.signals.drilldown.postings_for_score(session, score)` lists the
  postings behind any score.

## API

A read-only FastAPI service. Every route is a `GET` under `/api/v1`. Interactive docs are at
`http://127.0.0.1:8000/docs`.

| Route | Returns |
|-------|---------|
| `/health` | `ok`, or 503 `schema_missing`, plus the taxonomy and signals versions |
| `/meta` | Role families, seniorities, location kinds, signal levels and detectors (for filters) |
| `/companies`, `/companies/{board_token}` | Open-posting counts and the latest scrape |
| `/postings` | Filters: `company`, `role_family`, `seniority`, `country`, `open`. Up to 200 items per page, with a cursor (`next_cursor`) |
| `/postings/{id}` | One posting with its canonical locations and open/close history |
| `/signal-runs` | Runs, newest `as_of` first, with their params and versions |
| `/signals` | `run=latest` or an id; filters `detector`, `direction`, `level`, `company`, `min_abs_z`, `signals_only`. Raw z and inputs are included; `mix_shift` rows add `share_recent`/`share_baseline` and are marked `provisional` |
| `/signals/{id}` | One score, its run and the postings behind it (drill-down) |
| `/signals/trends?ids=…` | 1–50 scores: each cell's last 8 weeks (`value`, `z`), recomputed with the detector and the run's params. The last point equals the stored score. Uncovered weeks are `null` |
| `/companies/{token}/composition` | Open postings counted by role family, seniority and country (server-side) |
| `/company-trends?weeks=12` | Weekly `open_postings` and `new_postings` per company (`null` = no trustworthy scrape that week) |

**Security defaults**
- The server binds `127.0.0.1`. To bind anything else, `JOBSIGNAL_API_KEY` must be set, or the
  server refuses to start. Then every data route needs the `X-API-Key` header (compared in
  constant time); `/health` stays open.
- Always start the API with `scripts/run_api.py`. Running `uvicorn` directly bypasses the bind
  check.
- Errors never include tracebacks. CORS is off unless `JOBSIGNAL_API_CORS_ORIGINS` is set.

## Dashboard

A Streamlit dashboard for clients. It reads **only** the API, never the database.

```bash
uv run python scripts/run_api.py         # terminal 1
uv run python scripts/run_dashboard.py   # terminal 2 -> http://127.0.0.1:8501
```

| Tab | Shows |
|-----|-------|
| **Alerts** | KPI tiles with the change since the previous week's run; a z-score chart; alert groups (one event at several levels is one row, with "also at"), each with an 8-week sparkline, Δz vs the previous week and Δ vs baseline; per-alert detail with a plain-English explanation, a trend chart and the postings behind it |
| **Companies** | Open-postings and new-postings sparklines and Δ per company; composition charts; the postings table, filtered on the server, loaded 200 rows at a time (**Load 200 more**) |
| **Runs & health** | API status, versions, run history and parameters |

- **Bands:** red when |z| > 5, yellow when 3 ≤ |z| ≤ 5. The band is also shown as text.
- **Freshness:** API reads are cached for 60 s (**Refresh now** clears it). A warning names any
  company whose last scrape is older than 36 h or did not finish ok.
- **Trends start empty.** Volume trends need 8 covered weeks of scraping; until then they show
  gaps ("Not enough history yet"). `mix_shift` is provisional and labelled so.
- **Security:** binds 127.0.0.1 (`.streamlit/config.toml` and the launcher). Another host needs
  `--allow-remote` and prints a warning: the dashboard has **no login**. The API key stays on
  the server. Scraped titles and links are shown as plain text; only http(s) links are
  clickable. Usage statistics are off.

## Configuration

Settings load from `JOBSIGNAL_*` environment variables or a local `.env` file:

| Variable | Default | Purpose |
|----------|---------|---------|
| `JOBSIGNAL_DATABASE_URL` | `sqlite:///jobsignal.db` | SQLAlchemy URL (PostgreSQL in production) |
| `JOBSIGNAL_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `JOBSIGNAL_API_KEY` | *(empty)* | Required to bind the API beyond localhost; sent as `X-API-Key` |
| `JOBSIGNAL_API_CORS_ORIGINS` | *(empty)* | Comma-separated origins allowed by CORS (GET only) |
| `JOBSIGNAL_API_URL` | `http://127.0.0.1:8000` | Where the dashboard finds the API (http/https only) |
