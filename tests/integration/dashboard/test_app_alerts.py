from datetime import timedelta

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from jobsignal.api.app import create_app
from jobsignal.dashboard.client import ApiClient
from jobsignal.signals.detectors import SCORE_COLUMNS
from jobsignal.signals.params import DetectorParams
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import save_signal_run
from jobsignal.weeks import week_start
from tests.integration.conftest import T1, _score
from tests.integration.dashboard.conftest import count_requests, run_app, texts

pytestmark = pytest.mark.integration

KEY = "s3cret-app-key"  # gitleaks:allow - test fixture, not a credential
DOWN = (
    "Cannot reach the JobSignal API at http://127.0.0.1:9. "
    "Start it with: uv run python scripts/run_api.py"
)


def metrics(at) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def deltas(at) -> dict[str, str | None]:
    return {m.label: m.delta for m in at.metric}


def alerts_table(at) -> pd.DataFrame:
    return next(f.value for f in at.dataframe if "band" in f.value.columns)


def test_alerts_tab_renders_grouped_signals(seeded_api):
    at = run_app(ApiClient(seeded_api))
    assert not at.exception
    assert metrics(at) == {
        "Alerts": "2", "Expansions": "1", "Contractions": "1", "Companies with alerts": "1",
    }  # fmt: skip
    table = alerts_table(at)
    assert list(table["band"]) == ["yellow", "yellow"]
    assert list(table["z"]) == [-5.0, 3.2]
    assert all(len(cell) == 8 for cell in table["trend"])


def test_alerts_trends_fetched_in_one_request(seeded_api):
    paths = count_requests(seeded_api)
    run_app(ApiClient(seeded_api))
    assert paths["/api/v1/signals/trends"] == 1


def test_kpi_delta_vs_previous_week_run(seeded_api, migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        older = T1 + timedelta(days=1) - timedelta(weeks=1)
        contraction = _score(
            detector="volume", basis="observed", level="company", company="acme",
            week_start=week_start(older) - timedelta(weeks=1), observed=0.0,
            baseline_mean=25.0, baseline_std=1.0, z=-4.0, is_signal=True,
            direction="contraction", severity="strong",
        )  # fmt: skip
        frame = pd.DataFrame([contraction], columns=[*SCORE_COLUMNS, "basis", "level"])
        save_signal_run(session, older, older, DetectorParams(), frame)
        session.commit()
    engine.dispose()
    at = run_app(ApiClient(seeded_api))
    assert deltas(at) == {
        "Alerts": "1", "Expansions": "1", "Contractions": "0", "Companies with alerts": "0",
    }  # fmt: skip


def test_no_previous_week_run_means_no_delta(seeded_api):
    at = run_app(ApiClient(seeded_api))
    assert not any(deltas(at).values())  # AppTest reports 'no delta' as ''


def test_inspect_alert_shows_drilldown(seeded_api):
    at = run_app(ApiClient(seeded_api))
    expansion = int(alerts_table(at).set_index("z").loc[3.2, "id"])
    at.selectbox(key="inspect").select(expansion).run()
    assert not at.exception
    titles = [list(f.value["title"]) for f in at.dataframe if "title" in f.value.columns]
    assert ["Senior Account Executive"] in titles
    assert any(t.value.startswith("acme · sales · GB:") for t in at.text)


def test_filters_reach_the_api(seeded_api):
    at = run_app(ApiClient(seeded_api))
    at.selectbox(key="direction").select("contraction").run()
    assert list(alerts_table(at)["z"]) == [-5.0]
    assert metrics(at)["Alerts"] == "1"


def unreachable() -> httpx.Client:
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    return httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://127.0.0.1:9")


def test_api_down_shows_error():
    at = run_app(ApiClient(unreachable()))
    assert [e.value for e in at.error] == [DOWN]
    assert not at.exception
    assert len(at.tabs) == 0


def test_wrong_key_shows_auth_error_without_key(migrated_url, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_API_KEY", KEY)
    with TestClient(create_app(migrated_url), headers={"X-API-Key": "wrong"}) as client:
        at = run_app(ApiClient(client))
    assert [e.value for e in at.error] == [
        "The API rejected the request: set JOBSIGNAL_API_KEY to the API's key."
    ]
    assert not any("s3cret" in value for value in texts(at))


def test_schema_missing_shows_hint(db_url):
    with TestClient(create_app(db_url)) as client:
        at = run_app(ApiClient(client))
    assert len(at.error) == 1
    assert "alembic upgrade head" in at.error[0].value
    assert not at.exception


def test_no_runs_shows_info(api_client):
    at = run_app(ApiClient(api_client))
    assert "No signal runs yet. Run: uv run python scripts/run_detect.py" in [
        i.value for i in at.info
    ]
    assert not at.exception
