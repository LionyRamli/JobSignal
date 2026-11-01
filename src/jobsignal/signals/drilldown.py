"""The postings behind a stored score (for the dashboard's "why?" view)."""

import json
from datetime import timedelta

from sqlalchemy.orm import Session

from jobsignal.signals.events import to_frame
from jobsignal.signals.params import DetectorParams
from jobsignal.storage.repository import opening_rows
from jobsignal.storage.schema import Company, SignalRun, SignalScore


def postings_for_score(session: Session, score: SignalScore) -> list[int]:
    """Posting ids counted in ``score``'s cell and window.

    Uses the same event rules as detection: the observed cutoff, one row per country, and ZZ
    for unlocated postings. Role families are read as they are now, so if the run's
    taxonomy_version differs from the current one the list can differ slightly.
    """
    run = session.get(SignalRun, score.run_id)
    params = DetectorParams(**json.loads(run.params))
    company = session.get(Company, score.company_id).board_token
    events = to_frame(opening_rows(session, company=company), score.basis)  # this company only
    if score.detector == "volume":
        weeks = {score.week_start}
    else:
        weeks = {score.week_start - timedelta(weeks=k) for k in range(params.recent_weeks)}
    mask = (events["company"] == company) & events["event_week"].isin(weeks)
    if score.role_family is not None:
        mask &= events["role_family"] == score.role_family
    if score.country_code is not None:
        mask &= events["country"] == score.country_code
    return sorted(set(events.loc[mask, "posting_id"].tolist()))
