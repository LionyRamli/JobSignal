import json
from datetime import timedelta

import pandas as pd
import pytest

from jobsignal.signals.detectors import SCORE_COLUMNS
from jobsignal.signals.params import DetectorParams
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import save_signal_run
from tests.integration.api.conftest import T1

pytestmark = pytest.mark.integration


def zs(response):
    return [item["z"] for item in response.json()["items"]]


def test_latest_run_signals_by_abs_z(seeded_api):
    body = seeded_api.get("/api/v1/signals").json()
    assert [i["z"] for i in body["items"]] == [-5.0, 3.2]
    assert [i["direction"] for i in body["items"]] == ["contraction", "expansion"]
    assert body["run"]["params"]["baseline_weeks"] == 8
    assert body["run"]["as_of"].endswith("Z")


def test_signals_only_false_includes_scored_rows_nulls_last(seeded_api):
    assert zs(seeded_api.get("/api/v1/signals", params={"signals_only": "false"})) == [
        -5.0, 3.2, 1.0, None,
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"direction": "contraction"}, [-5.0]),
        ({"detector": "mix_shift", "signals_only": "false"}, [1.0]),
        ({"level": "company", "signals_only": "false"}, [-5.0, None]),
        ({"company": "beta", "signals_only": "false"}, [None]),
        ({"min_abs_z": 4}, [-5.0]),
    ],
)
def test_filters(seeded_api, params, expected):
    assert zs(seeded_api.get("/api/v1/signals", params=params)) == expected


def test_null_z_and_provisional_flags_serialise_cleanly(seeded_api):
    response = seeded_api.get("/api/v1/signals", params={"signals_only": "false"})

    def reject(constant):
        pytest.fail(f"non-JSON constant in body: {constant}")

    items = json.loads(response.text, parse_constant=reject)["items"]
    insufficient = next(i for i in items if i["status"] == "insufficient_history")
    assert insufficient["z"] is None
    assert insufficient["provisional"] is False
    mix = next(i for i in items if i["detector"] == "mix_shift")
    assert mix["provisional"] is True
    assert mix["share_recent"] == pytest.approx(0.3)
    assert mix["share_baseline"] == pytest.approx(10 / 150)
    volume = next(i for i in items if i["z"] == 3.2)
    assert (volume["share_recent"], volume["share_baseline"]) == (None, None)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_min_abs_z_must_be_finite(seeded_api, bad):
    assert seeded_api.get("/api/v1/signals", params={"min_abs_z": bad}).status_code == 422


def test_run_param(seeded_api):
    run_id = seeded_api.get("/api/v1/signals").json()["run"]["id"]
    assert seeded_api.get("/api/v1/signals", params={"run": str(run_id)}).status_code == 200
    assert seeded_api.get("/api/v1/signals", params={"run": "abc"}).status_code == 422
    assert seeded_api.get("/api/v1/signals", params={"run": "-1"}).status_code == 422
    missing = seeded_api.get("/api/v1/signals", params={"run": "999999"})
    assert (missing.status_code, missing.json()) == (404, {"detail": "signal run not found"})


def test_no_runs_yet_returns_null_run(api_client):
    assert api_client.get("/api/v1/signals").json() == {"run": None, "items": []}


def test_signal_detail_includes_drilldown_postings(seeded_api):
    expansion = next(i for i in seeded_api.get("/api/v1/signals").json()["items"] if i["z"] == 3.2)
    body = seeded_api.get(f"/api/v1/signals/{expansion['id']}").json()
    assert body["signal"]["id"] == expansion["id"]
    assert body["run"]["id"] == expansion["run_id"]
    # only posting 6 was first seen after the initial load, in sales / GB that week
    assert [p["title"] for p in body["postings"]] == ["Senior Account Executive"]
    assert body["postings"][0]["locations"][0]["country_code"] == "GB"


def test_unknown_signal_is_404(seeded_api):
    response = seeded_api.get("/api/v1/signals/999999")
    assert (response.status_code, response.json()) == (404, {"detail": "signal not found"})


def test_signal_runs_newest_as_of_first(seeded_api, migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        old = T1 - timedelta(days=30)  # a backtest computed later for an older week
        empty = pd.DataFrame(columns=[*SCORE_COLUMNS, "basis", "level"])
        save_signal_run(session, T1 + timedelta(days=5), old, DetectorParams(), empty)
        session.commit()
    engine.dispose()

    runs = seeded_api.get("/api/v1/signal-runs").json()
    assert [r["as_of"] for r in runs] == sorted((r["as_of"] for r in runs), reverse=True)
    assert len(runs) == 2
    assert runs[0]["taxonomy_version"]
