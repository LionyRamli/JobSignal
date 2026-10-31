# Tasks

## Active

- [ ] **Phase 1.1: Extraction** - planning (brainstorming → design doc → writing-plans → user approval)
  - ATSSource interface + first source via public JSON API, TDD against recorded fixtures
  - Shared HTTP client: rate limiting, retry/backoff, timeouts, user agent; security-and-hardening review

## Backlog

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
- [x] ~~Phase 0: Scaffold~~ (2026-10-31) - uv/ruff/pytest, config, logger, storage, alembic baseline, CI; 23 tests, 100% cov
