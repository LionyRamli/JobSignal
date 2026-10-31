# JobSignal — Project Memory

## Project
University CS project. **JobSignal** = predictive business intelligence from job-market data.
Companies show expansion plans through hiring before they announce them. JobSignal turns
scattered ATS postings into evidence-based indicators of expansion, investment priorities,
and B2B opportunities.

**Phase 1 focus:** detect localized ATS hiring anomalies (sudden spikes in roles or locations per company).
1. **Extract:** Python scrapers against unified ATS endpoints (Greenhouse, Lever, Workday, …)
2. **Harmonize:** NLP classification of job role + location
3. **Deliver:** predictive alerting dashboard

**Phase 2 (keep architecture open for):**
- Time-to-fill / posting duration → talent-crisis signal per sector
- Join with public stock price trends

## Terms
| Term | Meaning |
|------|---------|
| **ATS** | Applicant Tracking System (Greenhouse, Lever, Workday, Ashby…) |
| **Posting** | One job opening, as scraped |
| **Snapshot** | One scrape run's view of a company's open postings |
| **Signal / Anomaly** | Statistically unusual hiring change (role/location/volume) |
| **Harmonization** | Normalizing raw titles/locations into canonical taxonomy |

## Tech Stack
| Layer | Tools |
|-------|-------|
| Language | Python 3.12 |
| Scraping | playwright (dynamic pages), BeautifulSoup; prefer public JSON ATS APIs via HTTP client when available |
| NLP / data | spaCy, pandas |
| Storage | SQLite (local dev) → PostgreSQL (prod), via SQLAlchemy |
| API | FastAPI |
| Dashboard | Streamlit (default) or Dash |
| Tests | pytest |

## Project Config (verified facts only)
| Item | Value |
|------|-------|
| Python | 3.12.2 (system, only interpreter per `py -0`) |
| uv | 0.13.6 installed (pip 24.0 also available) |
| Git | 2.40.1, `main` → origin https://github.com/LionyRamli/JobSignal (CI: Actions `tests`); `gh` CLI not installed; feature work on branches → PR (opened by user in web UI) → merge |
| OS / shell | Windows 11, PowerShell + Git Bash; CI = ubuntu-latest |
| Install | `uv sync` (CI: `uv sync --locked`); add deps with `uv add <pkg>` / `uv add --dev <pkg>` |
| Test | `uv run pytest` · one file: `uv run pytest tests/unit/test_logger.py -q` · coverage: `--cov=jobsignal` |
| Lint / format | `uv run ruff check .` · `uv run ruff format --check .` (fix: `ruff check --fix .`, `ruff format .`) |
| Migrations | `uv run alembic upgrade head` · new: `uv run alembic revision --autogenerate -m "msg"` (ruff post-write hook auto-formats) |
| Env | `JOBSIGNAL_DATABASE_URL`, `JOBSIGNAL_LOG_LEVEL` via env or `.env` (see `.env.example`) |
| Scrape | `uv run alembic upgrade head` once, then `uv run python scripts/run_scrape.py anthropic databricks stripe [--db URL] [--out FILE]`; exit 0 ok / 1 a company failed or was incomplete / 2 schema missing. One writer at a time |
| Storage rules | closures only from complete fetches; failed snapshot posting_count is NULL; always filter `snapshots.status` in queries; times are aware UTC via `UTCDateTime` |
| Migrations gotcha | env.py `render_item` writes `UTCDateTime` as `sa.DateTime(timezone=True)`: migrations never import app code |
| Fixtures | `uv run python scripts/record_greenhouse_fixture.py <token> <out.json>` (1 live GET, trimmed) |
| ATS facts | Greenhouse: use `/v1/boards/{token}/departments` (jobs+dept, ~0.5 MB); OpenAI is on Ashby, not Greenhouse |
| httpx test gotcha | `httpx.Response(content=bytes)` decodes eagerly in the test; use `content=iter([...])` to exercise client-side decoding |
| Test gotchas | `tests/conftest.py` autouse fixture strips `JOBSIGNAL_*` env + chdirs to `tmp_path`; use `PROJECT_ROOT` for repo files |
| Windows encoding | Python default is cp1252: always pass `encoding="utf-8"` to `read_text`/`write_text`/`open` (a missing one truncated TASKS.md once) |
| Secret scan | pre-commit hook runs `gitleaks git --pre-commit --staged --redact` (`.pre-commit-config.yaml`; setup: `uv run pre-commit install`). Never bypass with `--no-verify`. History scan: `gitleaks git --redact .` |
| gitleaks PATH | winget install lives in `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gitleaks.Gitleaks_*`; a shell started before install lacks it — prepend that dir to PATH |
| Mutation check | tdd-skill `mutate-check.sh` calls `python3` → Windows Store stub; prepend a `python3`→`python` shim to PATH |

## Status
- **Done:** Phase 0 scaffold · 1.1 extraction (Greenhouse) · 1.2 storage (SQLite schema, history) — all on `main`, CI green
- **Next:** Phase 1.3 harmonization (role + location taxonomy)

## Approved Structure (2026-10-31)
- `src/jobsignal/` layout: `config.py`, `logger.py`, `models.py`, `extraction/`, `harmonization/`,
  `signals/`, `storage/`, `api/`, `pipeline.py`
- `alembic/` + `alembic.ini` at root → schema migrations for `storage/schema.py`
- `dashboard/` (Streamlit, API-only), `scripts/` (CLI), `tests/{fixtures,unit,integration}`
- Rules: one-way deps (extraction → harmonization → signals); one ATS interface;
  no live network in tests; snapshot every scrape run (enables Phase 2 duration analysis)
- Logging: one central setup in `logger.py`; modules call `logging.getLogger(__name__)`.
  INFO = run lifecycle, WARNING = retries/rate limits, ERROR = failed requests/parse errors

## Workflow Rules (mandatory)
1. **Plan before code** — brainstorming / writing-plans first; wait for user approval.
2. **TDD** — write failing pytest tests before implementation; systematic-debugging on failures.
3. **Evidence before assertions** — never claim something works without running it.
4. **Context tracking** — keep this file + `TASKS.md` current.
5. **Review** — code-review + security-and-hardening before finalizing a module
   (scraper: rate limits, backoff, IP-block handling, robots/ToS respect).

## Coding Preferences
- Token-efficient, clean architecture; small modules with clear boundaries
- Type hints everywhere; config through env vars / settings, never hardcoded secrets
- Scrapers behind a common interface so new ATS sources plug in without touching core logic
