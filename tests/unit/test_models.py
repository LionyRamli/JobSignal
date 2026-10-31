from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobsignal.models import Posting

FETCHED = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def make_posting(**overrides):
    fields = {
        "source": "greenhouse",
        "company": "anthropic",
        "external_id": "5456619008",
        "title": "Research Engineer",
        "location_raw": "San Francisco, CA | Seattle, WA",
        "department": "Research",
        "url": "https://job-boards.greenhouse.io/anthropic/jobs/5456619008",
        "first_published": None,
        "updated_at": None,
        "fetched_at": FETCHED,
    }
    fields.update(overrides)
    return Posting(**fields)


def test_posting_is_immutable():
    posting = make_posting()
    with pytest.raises(ValidationError):
        posting.title = "x"


def test_posting_strips_and_requires_title():
    assert make_posting(title="  ML Engineer ").title == "ML Engineer"
    with pytest.raises(ValidationError):
        make_posting(title="   ")


def test_posting_requires_external_id():
    with pytest.raises(ValidationError):
        make_posting(external_id=" ")


def test_posting_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        make_posting(fetched_at=datetime(2026, 10, 31))
    with pytest.raises(ValidationError):
        make_posting(first_published=datetime(2026, 10, 31))
    assert make_posting(updated_at=FETCHED).updated_at == FETCHED


def test_posting_round_trips_through_json():
    posting = make_posting(first_published=FETCHED)
    assert Posting.model_validate_json(posting.model_dump_json()) == posting


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,<script>", "ftp://x/y", "/relative", ""]
)
def test_posting_url_must_be_absolute_http(url):
    with pytest.raises(ValidationError):
        make_posting(url=url)


def test_posting_accepts_http_and_https_urls():
    assert (
        make_posting(url="http://stripe.com/jobs?gh_jid=1").url == "http://stripe.com/jobs?gh_jid=1"
    )


def test_field_limits_match_storage_columns():
    from jobsignal.models import DEPARTMENT_MAX, EXTERNAL_ID_MAX, TITLE_MAX

    assert (TITLE_MAX, DEPARTMENT_MAX, EXTERNAL_ID_MAX) == (512, 256, 64)


def test_overlong_title_is_truncated_not_rejected():
    posting = make_posting(title="Senior " + "x" * 600)
    assert len(posting.title) == 512
    assert posting.title.startswith("Senior x")


def test_overlong_department_is_truncated():
    assert len(make_posting(department="D" * 300).department) == 256


def test_overlong_external_id_is_rejected():
    assert make_posting(external_id="9" * 64).external_id == "9" * 64
    with pytest.raises(ValidationError):
        make_posting(external_id="9" * 65)
