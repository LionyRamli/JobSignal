from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from jobsignal.api.deps import get_session
from jobsignal.api.pagination import INT64_MAX
from jobsignal.api.schemas import (
    LocationOut,
    PostingBrief,
    SignalDetail,
    SignalOut,
    SignalRunOut,
    SignalsPage,
)
from jobsignal.signals.drilldown import postings_for_score
from jobsignal.storage.repository import get_postings, list_scores, list_signal_runs, resolve_run
from jobsignal.storage.schema import Company, SignalRun, SignalScore

router = APIRouter(tags=["signals"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/signal-runs", response_model=list[SignalRunOut])
def signal_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[SignalRunOut]:
    return [SignalRunOut.from_record(run) for run in list_signal_runs(session, limit)]


@router.get("/signals", response_model=SignalsPage)
def signals(
    session: SessionDep,
    run: str = "latest",
    detector: Literal["volume", "mix_shift"] | None = None,
    direction: Literal["expansion", "contraction"] | None = None,
    level: str | None = None,
    company: str | None = None,
    min_abs_z: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
    signals_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SignalsPage:
    try:
        resolved = resolve_run(session, run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if resolved is None:
        if run == "latest":
            return SignalsPage(run=None, items=[])
        raise HTTPException(status_code=404, detail="signal run not found")
    rows = list_scores(
        session,
        resolved.id,
        detector=detector,
        direction=direction,
        level=level,
        company=company,
        min_abs_z=min_abs_z,
        signals_only=signals_only,
        limit=limit,
    )
    return SignalsPage(
        run=SignalRunOut.from_record(resolved),
        items=[SignalOut.from_record(score, token) for score, token in rows],
    )


@router.get("/signals/{signal_id}", response_model=SignalDetail)
def signal_detail(
    signal_id: Annotated[int, Path(ge=1, le=INT64_MAX)], session: SessionDep
) -> SignalDetail:
    score = session.get(SignalScore, signal_id)
    if score is None:
        raise HTTPException(status_code=404, detail="signal not found")
    company = session.get(Company, score.company_id).board_token
    postings = [
        PostingBrief(
            id=row.id,
            title=row.title,
            url=row.url,
            locations=[LocationOut.model_validate(x, from_attributes=True) for x in row.locations],
        )
        for row in get_postings(session, postings_for_score(session, score))  # one bulk query
    ]
    return SignalDetail(
        signal=SignalOut.from_record(score, company),
        run=SignalRunOut.from_record(session.get(SignalRun, score.run_id)),
        postings=postings,
    )
