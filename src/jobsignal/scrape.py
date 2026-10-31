"""Scrape Greenhouse boards and persist runs, snapshots and postings.

    uv run alembic upgrade head          # once per database
    uv run python scripts/run_scrape.py anthropic databricks stripe [--db URL] [--out FILE]

Exit codes: 0 every company succeeded; 1 any company failed (the rest are still scraped);
2 the database schema is missing (run ``alembic upgrade head``).
"""

import argparse
import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import httpx
from sqlalchemy import Engine, inspect

from jobsignal.config import get_settings
from jobsignal.extraction.errors import ExtractionError
from jobsignal.extraction.greenhouse import GreenhouseSource
from jobsignal.extraction.http_client import HttpClient
from jobsignal.extraction.rate_limit import RateLimiter
from jobsignal.logger import setup_logging
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import (
    finish_run,
    get_or_create_company,
    record_failed_snapshot,
    record_snapshot,
    start_run,
)
from jobsignal.storage.schema import Base

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_COMPANY_FAILED, EXIT_NO_SCHEMA = 0, 1, 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Greenhouse job boards.")
    parser.add_argument("companies", nargs="+", help="Greenhouse board tokens, e.g. anthropic")
    parser.add_argument("--db", default=None, help="database URL (default: JOBSIGNAL_DATABASE_URL)")
    parser.add_argument("--out", type=Path, default=None, help="also export postings as .jsonl")
    parser.add_argument("--log-level", default=None, help="overrides JOBSIGNAL_LOG_LEVEL")
    return parser.parse_args(argv)


def _schema_ready(engine: Engine) -> bool:
    existing = set(inspect(engine).get_table_names())
    return set(Base.metadata.tables) <= existing


def _now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: list[str] | None = None,
    transport: httpx.BaseTransport | None = None,
    min_interval: float | None = None,
) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    companies = list(dict.fromkeys(args.companies))  # dedupe, keep order

    engine = make_engine(args.db or get_settings().database_url)
    try:
        if not _schema_ready(engine):
            logger.error("database schema missing; run: uv run alembic upgrade head")
            return EXIT_NO_SCHEMA
        return _scrape(companies, engine, args.out, transport, min_interval)
    finally:
        engine.dispose()


def _scrape(
    companies: list[str],
    engine: Engine,
    out: Path | None,
    transport: httpx.BaseTransport | None,
    min_interval: float | None,
) -> int:
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(min_interval) if min_interval is not None else None
    failed: list[str] = []
    total = 0

    with (
        make_session_factory(engine)() as session,
        HttpClient(transport=transport, rate_limiter=limiter) as http,
        out.open("w", encoding="utf-8", newline="\n") if out else nullcontext() as sink,
    ):
        run = start_run(session, _now())
        session.commit()
        source = GreenhouseSource(http)

        for token in companies:
            try:
                postings = source.fetch_postings(token)
            except ValueError as exc:  # invalid board token: never becomes a company row
                logger.error("company=%r rejected: %s", token, exc)
                failed.append(token)
                continue
            except ExtractionError as exc:
                logger.error("company=%r failed: %s: %s", token, type(exc).__name__, exc)
                company = get_or_create_company(session, source.name, token, _now())
                record_failed_snapshot(session, run, company, type(exc).__name__, _now())
                session.commit()
                failed.append(token)
                continue

            company = get_or_create_company(session, source.name, token, _now())
            fetched_at = postings[0].fetched_at if postings else _now()
            snapshot = record_snapshot(session, run, company, postings, fetched_at)
            session.commit()
            _export(sink, postings)
            total += snapshot.posting_count

        finish_run(session, run, _now())
        session.commit()
        logger.info(
            "scrape finished run_id=%d status=%s companies=%d failed=%d postings=%d",
            run.id,
            run.status,
            len(companies),
            len(failed),
            total,
        )
    return EXIT_COMPANY_FAILED if failed else EXIT_OK


def _export(sink: TextIO | None, postings: list) -> None:
    if sink is None:
        return
    for posting in postings:
        sink.write(posting.model_dump_json() + "\n")
