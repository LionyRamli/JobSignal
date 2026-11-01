from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

from jobsignal.api.app import create_app
from jobsignal.dashboard.client import (
    ApiAuthError,
    ApiClient,
    ApiNotFound,
    ApiSchemaMissing,
    ApiUnavailable,
)

pytestmark = pytest.mark.integration

KEY = "s3cret-dashboard-key"  # gitleaks:allow - test fixture, not a credential
DOWN = (
    "Cannot reach the JobSignal API at http://127.0.0.1:9. "
    "Start it with: uv run python scripts/run_api.py"
)


def counted(client: TestClient) -> Counter:
    """Count requests by path through an httpx event hook."""
    paths: Counter = Counter()
    client.event_hooks["request"].append(lambda request: paths.update([request.url.path]))
    return paths


def unreachable() -> httpx.Client:
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    return httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://127.0.0.1:9")


def test_companies_meta_and_aggregates_parse(seeded_api):
    api = ApiClient(seeded_api)
    assert [c.board_token for c in api.companies()] == ["acme", "beta"]
    assert len(api.meta().signal_levels) == 4
    assert api.composition("acme").open_postings == 4
    assert len(api.company_trends(weeks=3)) == 2


def test_signals_latest_and_filters(seeded_api):
    api = ApiClient(seeded_api)
    assert [s.z for s in api.signals().items] == [-5.0, 3.2]
    assert [s.z for s in api.signals(direction="contraction").items] == [-5.0]
    assert api.signals(signals_only=False).items[-1].z is None


def test_signal_detail_and_trends(seeded_api):
    api = ApiClient(seeded_api)
    expansion = next(s for s in api.signals().items if s.z == 3.2)
    assert [p.title for p in api.signal(expansion.id).postings] == ["Senior Account Executive"]
    assert api.signal_trends([expansion.id])[0].signal_id == expansion.id
    paths = counted(seeded_api)
    assert api.signal_trends([]) == []
    assert sum(paths.values()) == 0


def test_postings_page_is_one_request(seeded_api):
    api = ApiClient(seeded_api)
    paths = counted(seeded_api)
    page = api.postings_page(company="acme", limit=2)
    assert len(page.items) == 2
    assert page.next_cursor is not None
    assert paths == Counter({"/api/v1/postings": 1})
    rest = api.postings_page(company="acme", limit=2, cursor=page.next_cursor)
    assert [p.id for p in rest.items] != [p.id for p in page.items]


def test_health_schema_missing_returns_body(db_url):
    with TestClient(create_app(db_url)) as client:  # file exists, never migrated
        assert ApiClient(client).health().status == "schema_missing"


def test_not_found_maps_to_api_not_found(seeded_api):
    with pytest.raises(ApiNotFound, match="signal not found"):
        ApiClient(seeded_api).signal(999999)


def test_schema_missing_maps_to_api_schema_missing(db_url):
    with TestClient(create_app(db_url)) as client, pytest.raises(ApiSchemaMissing) as err:
        ApiClient(client).companies()
    assert "alembic upgrade head" in str(err.value)


def test_connection_error_maps_to_api_unavailable():
    with pytest.raises(ApiUnavailable) as err:
        ApiClient(unreachable()).companies()
    assert str(err.value) == DOWN


def test_auth_error_never_contains_key(migrated_url, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_API_KEY", KEY)
    app = create_app(migrated_url)
    with (
        TestClient(app, headers={"X-API-Key": "wrong"}) as client,
        pytest.raises(ApiAuthError) as err,
    ):
        ApiClient(client).companies()
    assert str(err.value) == "The API rejected the request: set JOBSIGNAL_API_KEY to the API's key."
    assert "s3cret" not in str(err.value) + repr(err.value)
