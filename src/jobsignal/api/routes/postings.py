from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from jobsignal.api.deps import get_session
from jobsignal.api.pagination import INT64_MAX, decode_cursor, encode_cursor
from jobsignal.api.schemas import PostingOut, PostingsPage
from jobsignal.storage.repository import get_posting, list_postings

router = APIRouter(tags=["postings"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/postings", response_model=PostingsPage)
def postings(
    session: SessionDep,
    company: str | None = None,
    role_family: str | None = None,
    seniority: str | None = None,
    country: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    open: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> PostingsPage:
    try:
        after_id = decode_cursor(cursor) if cursor is not None else None
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None
    rows = list_postings(
        session,
        company=company,
        role_family=role_family,
        seniority=seniority,
        country=country,
        open_only=open,
        after_id=after_id,
        limit=limit + 1,  # one extra row tells us whether another page exists
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].id) if len(rows) > limit else None
    return PostingsPage(items=[PostingOut.from_record(r) for r in page], next_cursor=next_cursor)


@router.get("/postings/{posting_id}", response_model=PostingOut)
def posting(
    posting_id: Annotated[int, Path(ge=1, le=INT64_MAX)], session: SessionDep
) -> PostingOut:
    row = get_posting(session, posting_id)
    if row is None:
        raise HTTPException(status_code=404, detail="posting not found")
    return PostingOut.from_record(row)
