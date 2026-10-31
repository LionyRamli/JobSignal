import logging

import pytest
from fastapi.testclient import TestClient

from jobsignal.api.app import create_app

pytestmark = pytest.mark.integration

KEY = "test-key-7f3a9c"  # gitleaks:allow - test fixture, not a credential


def client_for(url, **kwargs):
    return TestClient(create_app(url), **kwargs)


def test_no_key_configured_allows_requests(migrated_url):
    with client_for(migrated_url) as client:
        assert client.get("/api/v1/companies").status_code == 200


def test_api_key_enforced(migrated_url, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_API_KEY", KEY)
    with client_for(migrated_url) as client:
        missing = client.get("/api/v1/companies")
        wrong = client.get("/api/v1/companies", headers={"X-API-Key": "nope"})
        right = client.get("/api/v1/companies", headers={"X-API-Key": KEY})
        health = client.get("/api/v1/health")
    assert (missing.status_code, wrong.status_code, right.status_code) == (401, 401, 200)
    assert missing.json() == {"detail": "invalid or missing API key"}
    assert health.status_code == 200  # monitoring stays open


def test_every_data_route_requires_the_key(migrated_url, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_API_KEY", KEY)
    with client_for(migrated_url) as client:
        paths = [p for p in client.get("/openapi.json").json()["paths"] if "{" not in p]
        for path in paths:
            expected = 200 if path.endswith("/health") else 401
            assert client.get(path).status_code == expected, path


def test_key_value_never_echoed(migrated_url, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_API_KEY", KEY)
    with client_for(migrated_url) as client:
        response = client.get("/api/v1/companies", headers={"X-API-Key": KEY[:-1]})
    assert KEY not in response.text
    assert KEY[:-1] not in response.text


def test_internal_errors_are_opaque(migrated_url, monkeypatch, caplog):
    import jobsignal.api.routes.companies as companies

    def explode(*args, **kwargs):
        raise RuntimeError("secret path C:/db/jobsignal.db exploded")

    monkeypatch.setattr(companies, "company_summaries", explode)
    monkeypatch.setattr(logging.getLogger("jobsignal"), "propagate", True)
    with (
        caplog.at_level(logging.ERROR),
        client_for(migrated_url, raise_server_exceptions=False) as client,
    ):
        response = client.get("/api/v1/companies")
    assert (response.status_code, response.json()) == (500, {"detail": "internal error"})
    assert "exploded" not in response.text
    assert "Traceback" not in response.text
    assert any("exploded" in (r.exc_text or "") for r in caplog.records)


def test_cors_off_by_default(migrated_url):
    with client_for(migrated_url) as client:
        response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_configured_origin(migrated_url, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_API_CORS_ORIGINS", "http://localhost:8501")
    with client_for(migrated_url) as client:
        allowed = client.get("/api/v1/health", headers={"Origin": "http://localhost:8501"})
        other = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8501"
    assert "access-control-allow-origin" not in other.headers
