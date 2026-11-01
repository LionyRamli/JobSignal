"""Shared fixtures: a real SQLite file under tmp_path, migrated with Alembic, and an API
client over it, optionally seeded through the real repository path."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jobsignal.api.app import create_app
from jobsignal.harmonization.locations import parse_locations
from jobsignal.harmonization.roles import classify_title
from jobsignal.models import Posting
from jobsignal.signals.detectors import SCORE_COLUMNS
from jobsignal.signals.params import DetectorParams
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import (
    finish_run,
    get_or_create_company,
    record_snapshot,
    save_harmonization,
    save_signal_run,
    start_run,
)
from jobsignal.storage.schema import PostingRecord
from jobsignal.weeks import week_start
from tests.conftest import PROJECT_ROOT


@pytest.fixture
def db_url(monkeypatch, tmp_path):
    url = f"sqlite:///{(tmp_path / 'jobsignal-test.db').as_posix()}"
    monkeypatch.setenv("JOBSIGNAL_DATABASE_URL", url)
    return url


@pytest.fixture
def alembic_cfg():
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.fixture
def migrated_url(alembic_cfg, db_url):
    command.upgrade(alembic_cfg, "head")
    return db_url


@pytest.fixture
def session(migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # Monday
T1 = T0 + timedelta(days=7)

ACME = {  # external_id -> (title, location)
    "1": ("Account Executive", "London, UK"),
    "2": ("Software Engineer", "San Francisco, CA"),
    "3": ("Data Scientist", "New York City, NY"),
    "4": ("Recruiter", "Seattle, WA"),  # closes at T1
}
ACME_NEW_AT_T1 = {"6": ("Senior Account Executive", "London, UK")}
BETA = {"5": ("Product Manager", "Seattle, WA")}


def _postings(company, table, at):
    return [
        Posting(source="greenhouse", company=company, external_id=eid, title=title,
                location_raw=loc, department=None, url=f"https://x.io/{company}/{eid}",
                first_published=T0 - timedelta(days=3), updated_at=None, fetched_at=at)
        for eid, (title, loc) in table.items()
    ]  # fmt: skip


def _score(**fields):
    row = dict.fromkeys([*SCORE_COLUMNS, "basis", "level"])
    row.update(baseline_weeks=8, is_signal=False, status="scored")
    row.update(fields)
    return row


@pytest.fixture
def api_client(migrated_url):
    with TestClient(create_app(migrated_url)) as client:
        yield client


@pytest.fixture
def seeded_api(migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        acme = get_or_create_company(session, "greenhouse", "acme", T0)
        beta = get_or_create_company(session, "greenhouse", "beta", T0)
        for company, batch, at in [
            (acme, _postings("acme", ACME, T0), T0),
            (beta, _postings("beta", BETA, T0), T0),
            (acme, _postings("acme", {**ACME, **ACME_NEW_AT_T1}, T1)[:3]
             + _postings("acme", ACME_NEW_AT_T1, T1), T1),
            (beta, _postings("beta", BETA, T1), T1),
        ]:  # fmt: skip
            run = start_run(session, at)
            record_snapshot(session, run, company, batch, at)
            finish_run(session, run, at)
            session.commit()
        for row in session.query(PostingRecord):
            roles = classify_title(row.title, row.department)
            save_harmonization(session, row, roles, parse_locations(row.location_raw), "t", T1)
        session.commit()

        week = week_start(T1)
        scores = pd.DataFrame(
            [
                _score(detector="volume", basis="observed", level="company_family_country",
                       company="acme", role_family="sales", country="GB", week_start=week,
                       observed=6.0, baseline_mean=2.0, baseline_std=0.5, z=3.2, is_signal=True,
                       direction="expansion", severity="notable"),
                _score(detector="volume", basis="observed", level="company", company="acme",
                       week_start=week, observed=0.0, baseline_mean=25.0, baseline_std=1.0,
                       z=-5.0, is_signal=True, direction="contraction", severity="strong"),
                _score(detector="volume", basis="observed", level="company", company="beta",
                       week_start=week, observed=1.0, baseline_weeks=1,
                       status="insufficient_history"),
                _score(detector="mix_shift", basis="published", level="company_family",
                       company="acme", role_family="sales", week_start=week, observed=15.0,
                       baseline_mean=10.0, z=1.0, company_recent_total=50.0,
                       company_baseline_total=150.0),
            ],
            columns=[*SCORE_COLUMNS, "basis", "level"],
        )  # fmt: skip
        save_signal_run(
            session, T1 + timedelta(days=1), T1 + timedelta(days=1), DetectorParams(), scores
        )
        session.commit()
    engine.dispose()
    with TestClient(create_app(migrated_url)) as client:
        yield client
