"""Record a small, real Greenhouse /departments response as a test fixture.

Usage:
    uv run python scripts/record_greenhouse_fixture.py anthropic \
        tests/fixtures/greenhouse/departments_anthropic.json --jobs-per-dept 2 --max-depts 3

Makes ONE live request. Keeps the payload's real key structure and only drops items:
the first ``--max-depts`` departments that have jobs (``--jobs-per-dept`` jobs each), plus
the first department with no jobs, so tests see every shape the API really returns.
"""

import argparse
import json
from pathlib import Path

from jobsignal.extraction.http_client import HttpClient

API_BASE = "https://boards-api.greenhouse.io/v1/boards"


def trim(payload: dict, jobs_per_dept: int, max_depts: int) -> dict:
    departments = payload["departments"]
    with_jobs = [d for d in departments if d["jobs"]][:max_depts]
    empty = [d for d in departments if not d["jobs"]][:1]
    kept = [{**d, "jobs": d["jobs"][:jobs_per_dept]} for d in with_jobs] + empty
    return {**payload, "departments": kept}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("token")
    parser.add_argument("out", type=Path)
    parser.add_argument("--jobs-per-dept", type=int, default=2)
    parser.add_argument("--max-depts", type=int, default=3)
    args = parser.parse_args()

    with HttpClient() as http:
        payload = http.get_json(f"{API_BASE}/{args.token}/departments")

    fixture = trim(payload, args.jobs_per_dept, args.max_depts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    jobs = sum(len(d["jobs"]) for d in fixture["departments"])
    print(f"wrote {args.out}: {len(fixture['departments'])} departments, {jobs} jobs")


if __name__ == "__main__":
    main()
