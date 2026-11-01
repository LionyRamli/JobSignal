import pytest
from fastapi.testclient import TestClient

from jobsignal.api.app import create_app

pytestmark = pytest.mark.integration


def test_meta_lists_taxonomy(api_client):
    meta = api_client.get("/api/v1/meta").json()
    assert len(meta["role_families"]) == 16
    assert meta["seniorities"][0] == "intern"
    assert len(meta["seniorities"]) == 7
    assert meta["location_kinds"] == ["city", "region", "country", "remote"]
    assert len(meta["signal_levels"]) == 4
    assert meta["detectors"] == ["volume", "mix_shift"]


def test_companies_list_counts_open_postings(seeded_api):
    companies = seeded_api.get("/api/v1/companies").json()
    assert [(c["board_token"], c["open_postings"]) for c in companies] == [("acme", 4), ("beta", 1)]
    assert {c["last_snapshot_status"] for c in companies} == {"ok"}


def test_company_detail(seeded_api):
    body = seeded_api.get("/api/v1/companies/beta").json()
    assert (body["board_token"], body["source"], body["open_postings"]) == ("beta", "greenhouse", 1)


def test_unknown_company_is_404(seeded_api):
    response = seeded_api.get("/api/v1/companies/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "company not found"}


def test_empty_database_lists_are_empty(api_client):
    assert api_client.get("/api/v1/companies").json() == []


def test_timestamps_are_utc_z(seeded_api):
    stamp = seeded_api.get("/api/v1/companies/acme").json()["last_snapshot_at"]
    assert stamp == "2026-10-12T09:00:00Z"


def test_routes_503_without_schema(tmp_path):
    with TestClient(create_app(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")) as client:
        for path in ("/api/v1/companies", "/api/v1/meta"):
            response = client.get(path)
            assert response.status_code == 503, path
            assert "alembic upgrade head" in response.json()["detail"]
