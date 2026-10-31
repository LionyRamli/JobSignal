from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from jobsignal.api.deps import get_session
from jobsignal.api.schemas import Company
from jobsignal.storage.repository import company_summaries

router = APIRouter(tags=["companies"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/companies", response_model=list[Company])
def list_companies(session: SessionDep) -> list[Company]:
    return [Company(**row._asdict()) for row in company_summaries(session)]


@router.get("/companies/{board_token}", response_model=Company)
def get_company(board_token: str, session: SessionDep) -> Company:
    rows = company_summaries(session, board_token)
    if not rows:
        raise HTTPException(status_code=404, detail="company not found")
    return Company(**rows[0]._asdict())
