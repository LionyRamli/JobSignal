"""Turn stored postings into opening events (one row per posting and country)."""

from collections.abc import Iterable
from typing import Literal

import pandas as pd

from jobsignal.signals.params import UNKNOWN_COUNTRY
from jobsignal.storage.repository import OpeningRow
from jobsignal.weeks import week_start

COLUMNS = ["posting_id", "company", "role_family", "country", "event_week"]


def to_frame(rows: Iterable[OpeningRow], basis: Literal["observed", "published"]) -> pd.DataFrame:
    """Opening events for one basis.

    observed: postings first seen AFTER the company's first snapshot (the initial load shows
    pre-existing postings, which are not new openings). published: ATS first_published dates
    (survivorship-biased: only still-open postings are visible).
    """
    records = []
    for row in rows:
        if basis == "observed":
            cutoff = row.company_first_snapshot_at
            if cutoff is None or row.first_seen_at <= cutoff:
                continue
            when = row.first_seen_at
        else:
            if row.first_published is None:
                continue
            when = row.first_published
        records.append(
            (
                row.posting_id,
                row.company,
                row.role_family or "unclassified",
                row.country_code or UNKNOWN_COUNTRY,
                week_start(when),
            )
        )
    return pd.DataFrame.from_records(records, columns=COLUMNS).drop_duplicates()
