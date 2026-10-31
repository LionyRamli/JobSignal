"""Scrape Greenhouse boards and write one JSON line per posting.

    uv run python scripts/run_scrape.py anthropic databricks stripe [--out FILE]

Exit code 0 if every company succeeded, 1 if any failed (the rest are still scraped).
"""

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from jobsignal.extraction.errors import ExtractionError
from jobsignal.extraction.greenhouse import GreenhouseSource
from jobsignal.extraction.http_client import HttpClient
from jobsignal.extraction.rate_limit import RateLimiter
from jobsignal.logger import setup_logging

logger = logging.getLogger(__name__)


def _default_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("data") / "raw" / f"greenhouse-{stamp}.jsonl"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Greenhouse job boards to JSON Lines.")
    parser.add_argument("companies", nargs="+", help="Greenhouse board tokens, e.g. anthropic")
    parser.add_argument("--out", type=Path, default=None, help="output .jsonl path")
    parser.add_argument("--log-level", default=None, help="overrides JOBSIGNAL_LOG_LEVEL")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    transport: httpx.BaseTransport | None = None,
    min_interval: float | None = None,
) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    out: Path = args.out or _default_out()
    out.parent.mkdir(parents=True, exist_ok=True)

    limiter = RateLimiter(min_interval) if min_interval is not None else None
    failed: list[str] = []
    total = 0
    with (
        HttpClient(transport=transport, rate_limiter=limiter) as http,
        out.open("w", encoding="utf-8", newline="\n") as sink,
    ):
        source = GreenhouseSource(http)
        for company in args.companies:
            try:
                postings = source.fetch_postings(company)
            except (ExtractionError, ValueError) as exc:
                logger.error("company=%r failed: %s: %s", company, type(exc).__name__, exc)
                failed.append(company)
                continue
            for posting in postings:
                sink.write(posting.model_dump_json() + "\n")
            total += len(postings)

    logger.info(
        "scrape finished companies=%d failed=%d postings=%d out=%s",
        len(args.companies),
        len(failed),
        total,
        out,
    )
    return 1 if failed else 0
