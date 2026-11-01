from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from jobsignal.api.deps import get_now, get_session
from jobsignal.api.schemas import (
    Company,
    CompanyTrend,
    CompanyTrendPoint,
    CompositionOut,
    CountOut,
)
from jobsignal.signals.trend import company_trends
from jobsignal.storage.repository import (
    company_composition,
    company_summaries,
    ok_snapshot_stats,
)

router = APIRouter(tags=["companies"])
SessionDep = Annotated[Session, Depends(get_session)]
NOT_FOUND = "company not found"


@router.get("/companies", response_model=list[Company])
def list_companies(session: SessionDep) -> list[Company]:
    return [Company(**row._asdict()) for row in company_summaries(session)]


@router.get("/companies/{board_token}", response_model=Company)
def get_company(board_token: str, session: SessionDep) -> Company:
    rows = company_summaries(session, board_token)
    if not rows:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return Company(**rows[0]._asdict())


@router.get("/companies/{board_token}/composition", response_model=CompositionOut)
def composition(board_token: str, session: SessionDep) -> CompositionOut:
    """Open postings counted by role family, seniority and country (server-side aggregate)."""
    found = company_composition(session, board_token)
    if found is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)

    def counts(pairs):
        return [CountOut(key=key, count=n) for key, n in pairs]

    return CompositionOut(
        board_token=board_token,
        open_postings=found.open_postings,
        by_role_family=counts(found.by_role_family),
        by_seniority=counts(found.by_seniority),
        by_country=counts(found.by_country),
    )


@router.get("/company-trends", response_model=list[CompanyTrend])
def trends(
    session: SessionDep,
    now: Annotated[datetime, Depends(get_now)],
    weeks: Annotated[int, Query(ge=1, le=52)] = 12,
) -> list[CompanyTrend]:
    """Weekly open-postings and new-postings series for every company (oldest week first).

    Weeks without trustworthy scrape coverage have new_postings = null, never 0.
    """
    tokens = [row.board_token for row in company_summaries(session)]
    return [
        CompanyTrend(
            board_token=token,
            points=[
                CompanyTrendPoint(week_start=w, open_postings=o, new_postings=n)
                for w, o, n in points
            ],
        )
        for token, points in company_trends(ok_snapshot_stats(session), tokens, now, weeks)
    ]
