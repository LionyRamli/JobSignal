import json
import math
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from jobsignal.signals.detectors import SCORE_COLUMNS
from jobsignal.signals.params import DetectorParams
from jobsignal.storage.repository import get_or_create_company, latest_signals, save_signal_run
from jobsignal.storage.schema import SignalRun, SignalScore

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
WEEK = date(2026, 10, 26)


def score(**overrides):
    row = {
        "detector": "volume", "company": "acme", "role_family": "sales", "country": "US",
        "week_start": WEEK, "observed": 12.0, "baseline_mean": 5.0, "baseline_std": 0.756,
        "baseline_weeks": 8, "z": 3.13, "status": "scored", "is_signal": True,
        "direction": "expansion", "severity": "notable",
        "company_recent_total": None, "company_baseline_total": None,
        "basis": "observed", "level": "company_family_country",
    }  # fmt: skip
    row.update(overrides)
    return row


def frame(*rows):
    return pd.DataFrame(list(rows), columns=[*SCORE_COLUMNS, "basis", "level"])


@pytest.fixture
def acme(session):
    company = get_or_create_company(session, "greenhouse", "acme", NOW)
    session.commit()
    return company


def test_save_and_read_back_scores(session, acme):
    rows = frame(
        score(),
        score(
            z=-3.5, observed=0.0, direction="contraction", severity="notable", role_family="data"
        ),
        score(z=None, status="insufficient_history", is_signal=False, direction=None,
              severity=None, baseline_mean=None, baseline_std=None, baseline_weeks=3,
              role_family=None, country=None, level="company"),
    )  # fmt: skip
    run = save_signal_run(session, NOW, NOW, DetectorParams(), rows)
    session.commit()
    session.expire_all()

    stored = session.get(SignalRun, run.id)
    assert stored.computed_at == NOW
    assert json.loads(stored.params) == json.loads(DetectorParams().to_json())
    scores = session.scalars(select(SignalScore).order_by(SignalScore.id)).all()
    assert [(s.direction, s.z, s.company_id) for s in scores] == [
        ("expansion", 3.13, acme.id), ("contraction", -3.5, acme.id), (None, None, acme.id),
    ]  # fmt: skip
    assert scores[0].week_start == WEEK
    assert (scores[0].observed, scores[0].baseline_mean, scores[0].baseline_std) == (
        12.0,
        5.0,
        0.756,
    )
    assert scores[2].role_family is None
    assert scores[2].level == "company"


def test_latest_signals_from_newest_run_only_by_abs_z(session, acme):
    save_signal_run(session, NOW, NOW, DetectorParams(), frame(score(z=9.0)))
    later = NOW.replace(day=9)
    save_signal_run(
        session, later, later, DetectorParams(),
        frame(score(z=3.2), score(z=-5.0, direction="contraction", role_family="data"),
              score(z=1.0, is_signal=False, direction=None, severity=None, role_family="eng")),
    )  # fmt: skip
    session.commit()

    assert [s.z for s in latest_signals(session)] == [-5.0, 3.2]


def test_unknown_company_rejected(session, acme):
    with pytest.raises(ValueError, match="nobody"):
        save_signal_run(session, NOW, NOW, DetectorParams(), frame(score(company="nobody")))


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_non_finite_z_rejected(session, acme, bad):
    with pytest.raises(ValueError, match="finite"):
        save_signal_run(session, NOW, NOW, DetectorParams(), frame(score(z=bad)))
    assert session.scalar(select(func.count()).select_from(SignalRun)) == 0


def test_missing_columns_rejected(session, acme):
    with pytest.raises(ValueError, match="columns"):
        save_signal_run(session, NOW, NOW, DetectorParams(), frame(score()).drop(columns=["basis"]))


@pytest.mark.parametrize(
    "overrides",
    [{"detector": "magic"}, {"status": "great"}, {"level": "galaxy"},
     {"basis": "rumour"}, {"direction": "sideways"}],
)  # fmt: skip
def test_constraints(session, acme, overrides):
    with pytest.raises(IntegrityError):
        save_signal_run(session, NOW, NOW, DetectorParams(), frame(score(**overrides)))


def test_runs_are_append_only(session, acme):
    save_signal_run(session, NOW, NOW, DetectorParams(), frame(score()))
    save_signal_run(session, NOW, NOW, DetectorParams(), frame(score()))
    session.commit()
    assert session.scalar(select(func.count()).select_from(SignalRun)) == 2
    assert session.scalar(select(func.count()).select_from(SignalScore)) == 2


def test_empty_scores_still_record_the_run(session, acme):
    run = save_signal_run(session, NOW, NOW, DetectorParams(), frame())
    session.commit()
    assert run.id is not None


def test_run_records_taxonomy_version_and_mix_totals(session, acme):
    from jobsignal.harmonization.taxonomy import TAXONOMY_VERSION

    mix = score(
        detector="mix_shift",
        basis="published",
        observed=15.0,
        baseline_mean=10.0,
        baseline_std=None,
        company_recent_total=50.0,
        company_baseline_total=150.0,
    )
    run = save_signal_run(session, NOW, NOW, DetectorParams(), frame(mix))
    session.commit()
    session.expire_all()

    assert session.get(SignalRun, run.id).taxonomy_version == TAXONOMY_VERSION
    stored = session.scalars(select(SignalScore)).one()
    assert (stored.company_recent_total, stored.company_baseline_total) == (50.0, 150.0)


def test_backtest_run_does_not_hide_the_live_run(session, acme):
    live_as_of = NOW
    save_signal_run(session, NOW, live_as_of, DetectorParams(), frame(score(z=3.5)))
    later = NOW.replace(hour=9)  # a backtest computed AFTER the live run, for an older week
    backtest_as_of = NOW.replace(day=1, month=9)
    save_signal_run(session, later, backtest_as_of, DetectorParams(), frame(score(z=8.0)))
    session.commit()

    assert [s.z for s in latest_signals(session)] == [3.5]
