# Tasks

## Active

- [ ] **Phase 1.4: Merge `feat/phase-1.4-signals`** - waiting on user PR; branch CI must be green
- [ ] **Ops: schedule daily scrape → harmonize → detect** - the volume detector needs ≥ 8 continuously covered weeks; history is now the bottleneck

## Backlog

- [ ] **Phase 1.1b: AshbySource for OpenAI** - `api.ashbyhq.com/posting-api/job-board/openai`, same ATSSource interface
- [ ] **Phase 1.3 follow-up from live signals** - 'engagement manager' / 'field engineer' phrases put 'Community Engagement Manager, Data Centers' and 'Field Engineer, Data Center Design' into solutions_engineering (inflated the live Anthropic SE/US signal); label golden rows first
- [ ] **Phase 1.4 deferred** (final review) - recalibrate z threshold on real history (FPR 3-30x nominal under overdispersion); primary-level grouping across the 4 levels (dashboard); robust baseline; --as-of look-ahead in published basis; vacuous cold-start test, weak --as-of test, tautological uniform-growth test; consistency CHECKs; warn when postings not harmonized at current taxonomy; guard baseline_weeks >= 2; retention of repeated target weeks
- [ ] **Phase 1.3 deferred minors** (final review) - City, ST, Country triples; broad 1-token family phrases (data center, business partner, research economist, risk analyst, <x> recruiter); seniority edge cases (to the CEO, Fellow, Associate GC); remote edge cases (Remote - IN, Remote - US & Canada, Remote - Anywhere); harmonize perf at 100k; single harmonize runner; version length assert; stronger version-bump test; golden tail coverage
- [ ] **Phase 1.2 deferred minors** (final review) - run status vs exit code on rejected tokens; InvalidTokenError; schema check creates empty .db / OperationalError traceback; per-snapshot load of all history; test comment on SQLite var limit; repo tests read via identity map; doc closed_at bound + julianday durations
- [ ] **Phase 1.1 deferred minors** (from final review) - naive timestamps drop job; Content-Length isascii; `--log-level` validation; atomic `--out` write; dedupe company args; strict job-id parsing
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
- [x] ~~Phase 1.4: Signal detection~~ (2026-11-01) - volume + mix_shift detectors (expansion + contraction), coverage-based week availability, storage with raw values, detect CLI, drill-down; 387 tests; live: 1 provisional signal (anthropic SE/US z=+3.27)
- [x] ~~Phase 1.3: merged to main via PR, CI green, branch deleted~~ (2026-11-01)
- [x] ~~Phase 1.3: Harmonization~~ (2026-11-01) - spaCy rules + gazetteer, storage, harmonize CLI; golden holdout family 94% / seniority 100% / locations 100%; live other 0.6%, unresolved 1.1%; 314 tests
- [x] ~~Phase 1.2: merged to main via PR #4 (ce6c008), CI green, branch deleted~~ (2026-11-01)
- [x] ~~Phase 1.2: Storage~~ (2026-11-01) - 5-table schema + migration, UTCDateTime, repository, CLI persistence; 192 tests; live: 2 runs, 2322 postings, no duplicates
- [x] ~~Pre-commit gitleaks secret scan~~ (2026-11-01) - blocks staged secrets (verified with a fake token); full-history scan clean
- [x] ~~Phase 1.1: merged to main via PR #1 (613120e), CI green, branch deleted~~ (2026-11-01)
- [x] ~~Phase 1.1: Extraction (Greenhouse)~~ (2026-10-31) - ATSSource, RateLimiter, hardened HttpClient, GreenhouseSource, scrape CLI; 128 tests; live: anthropic 675 / databricks 901 / stripe 746
- [x] ~~Phase 0: Scaffold~~ (2026-10-31) - uv/ruff/pytest, config, logger, storage, alembic baseline, CI; 23 tests, 100% cov
