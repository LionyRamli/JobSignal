# Tasks

## Active

- [ ] **Phase 1.1: Merge `feat/phase-1.1-extraction` into main** - waiting on user OK; branch CI must be green

## Backlog

- [ ] **Phase 1.1b: AshbySource for OpenAI** - `api.ashbyhq.com/posting-api/job-board/openai`, same ATSSource interface
- [ ] **Phase 1.1 deferred minors** (from final review) - naive timestamps drop job; Content-Length isascii; `--log-level` validation; atomic `--out` write; dedupe company args; strict job-id parsing
- [ ] **Install gitleaks + pre-commit secret scan** - not installed; manual sweep only so far
- [ ] **Phase 1.2: Storage** - schema for companies, postings, snapshots (SQLite)
- [ ] **Phase 1.3: Harmonization** - spaCy/rule-based role + location classification
- [ ] **Phase 1.4: Signal detection** - hiring-anomaly scoring per company/role/location
- [ ] **Phase 1.5: API** - FastAPI endpoints for signals & postings
- [ ] **Phase 1.6: Dashboard** - Streamlit alerting dashboard
- [ ] **Phase 1.7: Review & hardening** - code-review + security-and-hardening per module

## Waiting On

## Someday

- [ ] **Phase 2: Posting duration** - time-to-fill as talent-crisis indicator
- [ ] **Phase 2: Stock correlation** - join hiring signals with public stock trends
- [ ] **Migrate SQLite → PostgreSQL**

## Done

- [x] ~~Create CLAUDE.md and TASKS.md~~ (2026-10-31)
- [x] ~~Approve folder structure (+ alembic, central logging)~~ (2026-10-31)
- [x] ~~Phase 0: Initial commit, push, CI green on GitHub (run 41214004282)~~ (2026-10-31)
- [x] ~~Phase 1.1: Extraction (Greenhouse)~~ (2026-10-31) - ATSSource, RateLimiter, hardened HttpClient, GreenhouseSource, scrape CLI; 128 tests; live: anthropic 675 / databricks 901 / stripe 746
- [x] ~~Phase 0: Scaffold~~ (2026-10-31) - uv/ruff/pytest, config, logger, storage, alembic baseline, CI; 23 tests, 100% cov
