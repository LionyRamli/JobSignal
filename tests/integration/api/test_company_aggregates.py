from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from jobsignal.api.app import create_app
from jobsignal.api.deps import get_now
from jobsignal.weeks import week_start
from tests.integration.conftest import T0, T1

pytestmark = pytest.mark.integration

KEY = "test-key-agg-2b71"  # gitleaks:allow - test fixture, not a credential


def statements_for(client, path, **params):
    recorded = []

    def record(conn, cursor, statement, *args):
        if "sqlite_master" not in statement and not statement.startswith("PRAGMA"):
            recorded.append(statement)

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert client.get(path, params=params).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return recorded


def test_composition_counts(seeded_api):
    # acme open postings: 1 Account Executive (GB), 2 Software Engineer (US),
    # 3 Data Scientist (US), 6 Senior Account Executive (GB); 4 closed at T1
    body = seeded_api.get("/api/v1/companies/acme/composition").json()
    assert body["board_token"] == "acme"
    assert body["open_postings"] == 4
    assert body["by_role_family"] == [
        {"key": "sales", "count": 2},
        {"key": "data", "count": 1},
        {"key": "software_engineering", "count": 1},
    ]
    assert body["by_seniority"] == [{"key": "mid", "count": 3}, {"key": "senior", "count": 1}]
    assert body["by_country"] == [{"key": "GB", "count": 2}, {"key": "US", "count": 2}]


def test_composition_unknown_company_is_404(seeded_api):
    response = seeded_api.get("/api/v1/companies/nope/composition")
    assert (response.status_code, response.json()) == (404, {"detail": "company not found"})


def test_company_trends_weeks_and_gaps(seeded_api):
    seeded_api.app.dependency_overrides[get_now] = lambda: T1 + timedelta(days=1)
    try:
        body = seeded_api.get("/api/v1/company-trends", params={"weeks": 3}).json()
    finally:
        seeded_api.app.dependency_overrides.clear()
    assert [t["board_token"] for t in body] == ["acme", "beta"]
    acme = body[0]["points"]
    expected_weeks = [week_start(T1) - timedelta(weeks=k) for k in (2, 1, 0)]
    assert [p["week_start"] for p in acme] == [w.isoformat() for w in expected_weeks]
    assert [p["open_postings"] for p in acme] == [None, 4, 4]
    # the first-snapshot week is never covered: its 'new' postings are the initial load
    t0_point = next(p for p in acme if p["week_start"] == week_start(T0).isoformat())
    assert t0_point["new_postings"] is None


@pytest.mark.parametrize("weeks", [0, 53])
def test_company_trends_weeks_bounds(seeded_api, weeks):
    assert seeded_api.get("/api/v1/company-trends", params={"weeks": weeks}).status_code == 422


def test_aggregates_statement_count_is_constant(seeded_api):
    assert len(statements_for(seeded_api, "/api/v1/companies/acme/composition")) <= 4
    assert len(statements_for(seeded_api, "/api/v1/company-trends", weeks=12)) <= 4


def test_aggregates_require_key(migrated_url, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_API_KEY", KEY)
    with TestClient(create_app(migrated_url)) as client:
        assert client.get("/api/v1/companies/acme/composition").status_code == 401
        assert client.get("/api/v1/company-trends").status_code == 401
