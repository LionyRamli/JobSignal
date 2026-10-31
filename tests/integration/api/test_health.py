from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from jobsignal.api.app import create_app
from jobsignal.harmonization.taxonomy import TAXONOMY_VERSION
from jobsignal.signals.params import SIGNALS_VERSION

pytestmark = pytest.mark.integration


def test_health_ok(api_client):
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "taxonomy_version": TAXONOMY_VERSION,
        "signals_version": SIGNALS_VERSION,
    }


def test_health_schema_missing(tmp_path):
    with TestClient(create_app(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["status"] == "schema_missing"


def test_openapi_lists_only_get_routes(api_client):
    paths = api_client.get("/openapi.json").json()["paths"]
    assert paths  # at least health
    assert {method for ops in paths.values() for method in ops} == {"get"}
    assert all(path.startswith("/api/v1/") for path in paths)


def test_sqlite_usable_across_threads(api_client):
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _: api_client.get("/api/v1/health").status_code, range(20)))
    assert codes == [200] * 20
