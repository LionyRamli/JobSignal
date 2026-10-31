import copy
import json
import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jobsignal.extraction.base import ATSSource
from jobsignal.extraction.errors import InvalidPayloadError, SourceNotFoundError
from jobsignal.extraction.greenhouse import API_BASE, GreenhouseSource
from jobsignal.extraction.http_client import HttpClient
from tests.conftest import PROJECT_ROOT

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "greenhouse"
FETCHED = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StubHttp(HttpClient):
    """Returns a canned payload (or raises) and records requested URLs. No network."""

    def __init__(self, payload=None, error=None):  # deliberately skips HttpClient.__init__
        self.payload = payload
        self.error = error
        self.urls: list[str] = []

    def get_json(self, url, params=None):
        self.urls.append(url)
        if self.error:
            raise self.error
        return copy.deepcopy(self.payload)


def source_for(payload=None, error=None):
    http = StubHttp(payload, error)
    return GreenhouseSource(http, clock=lambda: FETCHED), http


def test_is_an_ats_source_named_greenhouse():
    source, _ = source_for(load("departments_empty.json"))
    assert isinstance(source, ATSSource)
    assert GreenhouseSource.name == "greenhouse"


def test_requests_departments_endpoint():
    source, http = source_for(load("departments_anthropic.json"))
    source.fetch_postings("anthropic")
    assert API_BASE == "https://boards-api.greenhouse.io/v1/boards"
    assert http.urls == ["https://boards-api.greenhouse.io/v1/boards/anthropic/departments"]


def test_maps_fixture_job_to_posting():
    source, _ = source_for(load("departments_anthropic.json"))
    posting = source.fetch_postings("anthropic")[0]

    assert posting.source == "greenhouse"
    assert posting.company == "anthropic"
    assert posting.external_id == "4017331008"
    assert posting.title == "Research Engineer, Knowledge Team"
    assert posting.location_raw == (
        "Remote-Friendly (Travel-Required) | San Francisco, CA | Seattle, WA | New York City, NY"
    )
    assert posting.department == "AI Research & Engineering"
    assert posting.url == "https://job-boards.greenhouse.io/anthropic/jobs/4017331008"
    edt = timezone(timedelta(hours=-4))
    assert posting.first_published == datetime(2024, 4, 23, 16, 6, 5, tzinfo=edt)
    assert posting.updated_at == datetime(2026, 8, 21, 12, 49, 34, tzinfo=edt)
    assert posting.fetched_at == FETCHED


def test_returns_all_jobs_in_fixture():
    source, _ = source_for(load("departments_anthropic.json"))
    postings = source.fetch_postings("anthropic")
    assert len(postings) == 6
    assert len({p.external_id for p in postings}) == 6


def test_job_in_two_departments_returned_once():
    payload = load("departments_anthropic.json")
    first_job = payload["departments"][0]["jobs"][0]
    payload["departments"][1]["jobs"].append(copy.deepcopy(first_job))
    source, _ = source_for(payload)

    postings = source.fetch_postings("anthropic")

    matches = [p for p in postings if p.external_id == "4017331008"]
    assert len(postings) == 6
    assert [p.department for p in matches] == ["AI Research & Engineering"]


def test_no_department_bucket_maps_to_none():
    payload = load("departments_empty.json")
    payload["departments"][0]["jobs"].append(
        copy.deepcopy(load("departments_anthropic.json")["departments"][0]["jobs"][0])
    )
    source, _ = source_for(payload)
    assert source.fetch_postings("anthropic")[0].department is None


def test_empty_board_returns_empty_list():
    source, _ = source_for(load("departments_empty.json"))
    assert source.fetch_postings("anthropic") == []


def test_missing_location_and_dates_become_none():
    payload = load("departments_anthropic.json")
    job = payload["departments"][0]["jobs"][0]
    del job["location"]
    job["first_published"] = None
    del job["updated_at"]
    source, _ = source_for(payload)
    posting = source.fetch_postings("anthropic")[0]
    assert (posting.location_raw, posting.first_published, posting.updated_at) == (None,) * 3


def test_malformed_job_is_skipped_with_warning(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("jobsignal"), "propagate", True)
    payload = load("departments_anthropic.json")
    del payload["departments"][0]["jobs"][1]["title"]  # job 4017544008
    source, _ = source_for(payload)

    with caplog.at_level(logging.WARNING, logger="jobsignal.extraction.greenhouse"):
        postings = source.fetch_postings("anthropic")

    assert len(postings) == 5
    assert "4017544008" not in {p.external_id for p in postings}
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "4017544008" in warnings[0]


@pytest.mark.parametrize(
    "payload",
    [{"jobs": []}, {"departments": "nope"}, [], {"departments": [{"name": "no id", "jobs": []}]}],
)
def test_wrong_top_level_shape_raises_invalid_payload(payload):
    source, _ = source_for(payload)
    with pytest.raises(InvalidPayloadError):
        source.fetch_postings("anthropic")


@pytest.mark.parametrize(
    "token",
    [
        "../admin",
        "stripe/jobs?x=1",
        "",
        "Stripe ",
        "a" * 65,
        "-stripe",
        "str ipe",
        "stripe\n",
        "stripe/../admin",
        "acme.com",
        "stripe?content=true",
    ],
)
def test_invalid_board_token_rejected_without_request(token):
    source, http = source_for(load("departments_empty.json"))
    with pytest.raises(ValueError, match="board token"):
        source.fetch_postings(token)
    assert http.urls == []


@pytest.mark.parametrize("token", ["stripe", "databricks", "a" * 64, "acme_corp-2"])
def test_valid_board_tokens_accepted(token):
    source, http = source_for(load("departments_empty.json"))
    source.fetch_postings(token)
    assert http.urls == [f"{API_BASE}/{token}/departments"]


def test_unknown_board_propagates_source_not_found():
    source, _ = source_for(error=SourceNotFoundError("404"))
    with pytest.raises(SourceNotFoundError):
        source.fetch_postings("nosuchboard")


def test_logs_run_start_and_count(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("jobsignal"), "propagate", True)
    source, _ = source_for(load("departments_anthropic.json"))
    with caplog.at_level(logging.INFO, logger="jobsignal.extraction.greenhouse"):
        source.fetch_postings("anthropic")
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any("company=anthropic" in m for m in info)
    assert any("company=anthropic" in m and "postings=6" in m for m in info)


def test_job_with_unsafe_url_is_skipped():
    payload = load("departments_anthropic.json")
    payload["departments"][0]["jobs"][0]["absolute_url"] = "javascript:alert(document.cookie)"
    source, _ = source_for(payload)
    assert "4017331008" not in {p.external_id for p in source.fetch_postings("anthropic")}


def test_malformed_job_id_cannot_forge_log_lines(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("jobsignal"), "propagate", True)
    payload = load("departments_anthropic.json")
    job = payload["departments"][0]["jobs"][0]
    job["id"] = "1\n2026-10-31 00:00:00 ERROR jobsignal: forged"
    source, _ = source_for(payload)
    with caplog.at_level(logging.WARNING, logger="jobsignal.extraction.greenhouse"):
        source.fetch_postings("anthropic")
    messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(messages) == 1
    assert "\n" not in messages[0]


@pytest.mark.parametrize("bad_job", [None, "job", 42, ["list"]])
def test_non_object_job_is_skipped_not_fatal(bad_job, caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("jobsignal"), "propagate", True)
    payload = load("departments_anthropic.json")
    payload["departments"][0]["jobs"].insert(0, bad_job)
    source, _ = source_for(payload)
    with caplog.at_level(logging.WARNING, logger="jobsignal.extraction.greenhouse"):
        postings = source.fetch_postings("anthropic")
    assert len(postings) == 6
    assert sum(r.levelname == "WARNING" for r in caplog.records) == 1


def test_department_with_null_name_keeps_its_jobs_without_department():
    payload = load("departments_anthropic.json")
    payload["departments"][0]["name"] = None
    source, _ = source_for(payload)
    postings = source.fetch_postings("anthropic")
    assert len(postings) == 6
    assert postings[0].department is None


def test_department_with_null_jobs_is_skipped_others_kept():
    payload = load("departments_anthropic.json")
    payload["departments"][0]["jobs"] = None  # holds 2 of the 6 jobs
    source, _ = source_for(payload)
    assert len(source.fetch_postings("anthropic")) == 4


def test_fetch_reports_complete_board():
    source, _ = source_for(load("departments_anthropic.json"))
    result = source.fetch("anthropic")
    assert (len(result.postings), result.skipped, result.complete) == (6, 0, True)


@pytest.mark.parametrize(
    "break_payload",
    [
        lambda p: p["departments"][0].__setitem__("jobs", None),
        lambda p: p["departments"][0]["jobs"].insert(0, None),
        lambda p: p["departments"][0]["jobs"][0].__setitem__("absolute_url", "javascript:x"),
    ],
)
def test_fetch_reports_incomplete_board(break_payload):
    payload = load("departments_anthropic.json")
    break_payload(payload)
    source, _ = source_for(payload)
    result = source.fetch("anthropic")
    assert result.complete is False
    assert result.skipped >= 1
