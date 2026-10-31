"""Sample real postings for a hand-labelled golden set (labels are filled in by a human).

uv run python scripts/sample_golden.py jobsignal.db tests/fixtures/harmonization/golden_titles.csv
"""

import argparse
import csv
import random
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--holdout", type=float, default=0.25)
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    rows = con.execute(
        "SELECT c.board_token, p.title, COALESCE(p.department, '') FROM postings p "
        "JOIN companies c ON c.id = p.company_id ORDER BY c.board_token, p.external_id"
    ).fetchall()
    rng = random.Random(args.seed)  # noqa: S311 - reproducible sampling, not crypto
    by_company: dict[str, list[tuple[str, str]]] = {}
    for company, title, department in rows:
        by_company.setdefault(company, []).append((title, department))
    per_company = args.n // len(by_company)
    sample = [
        (company, *row)
        for company, items in sorted(by_company.items())
        for row in rng.sample(items, min(per_company, len(items)))
    ]
    rng.shuffle(sample)
    holdout = set(rng.sample(range(len(sample)), round(len(sample) * args.holdout)))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["company", "title", "department", "family", "seniority", "split"])
        for i, (company, title, department) in enumerate(sample):
            writer.writerow(
                [company, title, department, "", "", "holdout" if i in holdout else "tune"]
            )
    print(f"wrote {len(sample)} rows ({len(holdout)} holdout) to {args.out}")


if __name__ == "__main__":
    main()
