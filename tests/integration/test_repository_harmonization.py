from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobsignal.harmonization.locations import CanonicalLocation, LocationKind, LocationParse
from jobsignal.harmonization.roles import RoleClassification
from jobsignal.harmonization.taxonomy import RoleFamily, Seniority
from jobsignal.storage.repository import (
    get_or_create_company,
    postings_to_harmonize,
    save_harmonization,
)
from jobsignal.storage.schema import Location, PostingRecord, posting_locations

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
SF = CanonicalLocation(LocationKind.CITY, "US", "US-CA", "San Francisco")
REMOTE_US = CanonicalLocation(LocationKind.REMOTE, "US", None, None)
LONDON = CanonicalLocation(LocationKind.CITY, "GB", "GB-ENG", "London")
SWE_SENIOR = RoleClassification(RoleFamily.SOFTWARE_ENGINEERING, Seniority.SENIOR, ("sr",))


@pytest.fixture
def company(session):
    return get_or_create_company(session, "greenhouse", "anthropic", NOW)


def add_posting(session, company, external_id, **fields):
    row = PostingRecord(
        company_id=company.id,
        external_id=external_id,
        title="Engineer",
        url=f"https://example.com/{external_id}",
        first_seen_at=NOW,
        last_seen_at=NOW,
        **fields,
    )
    session.add(row)
    session.flush()
    return row


def linked_keys(session, posting):
    return sorted(
        session.scalars(
            select(Location.key)
            .join(posting_locations, posting_locations.c.location_id == Location.id)
            .where(posting_locations.c.posting_id == posting.id)
        )
    )


def test_save_sets_columns_and_links_locations(session, company):
    posting = add_posting(session, company, "1")
    save_harmonization(session, posting, SWE_SENIOR, LocationParse((SF, REMOTE_US), ()), "v1", NOW)
    session.commit()
    session.expire_all()

    row = session.get(PostingRecord, posting.id)
    assert (row.role_family, row.seniority, row.taxonomy_version, row.harmonized_at) == (
        "software_engineering",
        "senior",
        "v1",
        NOW,
    )
    assert linked_keys(session, row) == sorted([SF.key, REMOTE_US.key])
    location = session.scalar(select(Location).where(Location.key == SF.key))
    assert (location.kind, location.country_code, location.region_code, location.city) == (
        "city",
        "US",
        "US-CA",
        "San Francisco",
    )


def test_save_replaces_previous_locations(session, company):
    posting = add_posting(session, company, "1")
    save_harmonization(session, posting, SWE_SENIOR, LocationParse((SF,), ()), "v1", NOW)
    save_harmonization(session, posting, SWE_SENIOR, LocationParse((LONDON,), ()), "v2", LATER)
    session.commit()

    assert linked_keys(session, posting) == [LONDON.key]
    assert posting.taxonomy_version == "v2"


def test_save_with_no_locations_clears_links(session, company):
    posting = add_posting(session, company, "1")
    save_harmonization(session, posting, SWE_SENIOR, LocationParse((SF,), ()), "v1", NOW)
    save_harmonization(session, posting, SWE_SENIOR, LocationParse((), ("N/A",)), "v1", NOW)
    session.commit()
    assert linked_keys(session, posting) == []


def test_locations_shared_across_postings(session, company):
    for external_id in ("1", "2"):
        posting = add_posting(session, company, external_id)
        save_harmonization(session, posting, SWE_SENIOR, LocationParse((SF,), ()), "v1", NOW)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Location)) == 1
    assert session.scalar(select(func.count()).select_from(posting_locations)) == 2


def test_postings_to_harmonize_selects_missing_and_outdated(session, company):
    fresh = add_posting(session, company, "1")
    outdated = add_posting(session, company, "2", taxonomy_version="old")
    current = add_posting(session, company, "3", taxonomy_version="v1")
    session.commit()

    pending = postings_to_harmonize(session, "v1", limit=100)

    assert [p.id for p in pending] == [fresh.id, outdated.id]
    assert current.id not in {p.id for p in pending}


def test_limit_and_order(session, company):
    ids = [add_posting(session, company, str(i)).id for i in range(5)]
    session.commit()
    assert [p.id for p in postings_to_harmonize(session, "v1", limit=2)] == ids[:2]
