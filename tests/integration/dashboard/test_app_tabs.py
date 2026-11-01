import math
from collections import Counter
from datetime import timedelta
from numbers import Real

import pandas as pd
import pytest
from sqlalchemy import update

import jobsignal.dashboard.app as app_module
from jobsignal.dashboard.client import ApiClient, ApiUnavailable
from jobsignal.models import Posting
from jobsignal.signals.detectors import SCORE_COLUMNS
from jobsignal.signals.params import DetectorParams
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import (
    finish_run,
    get_or_create_company,
    record_snapshot,
    save_signal_run,
    start_run,
)
from jobsignal.storage.schema import PostingRecord
from tests.integration.conftest import T0, T1
from tests.integration.dashboard.conftest import chart_cells, count_requests, run_app

pytestmark = pytest.mark.integration

HOSTILE_TITLE = "<script>x</script> [win](javascript:alert(1))"


def frame_with(at, column) -> pd.DataFrame:
    return next(f.value for f in at.dataframe if column in f.value.columns)


def postings_table(at) -> pd.DataFrame:
    return next(f.value for f in at.dataframe if {"title", "seniority"} <= set(f.value.columns))


def record_queries(http_client) -> list[tuple[str, dict]]:
    seen: list[tuple[str, dict]] = []
    http_client.event_hooks["request"].append(
        lambda request: seen.append((request.url.path, dict(request.url.params)))
    )
    return seen


def test_stale_warning_names_companies(seeded_api):
    at = run_app(ApiClient(seeded_api))
    warnings = [w.value for w in at.warning if w.value.startswith("Data out of date:")]
    assert len(warnings) == 1
    assert "acme" in warnings[0]
    assert "beta" in warnings[0]


def test_render_request_budget(seeded_api):
    paths = count_requests(seeded_api)
    at = run_app(ApiClient(seeded_api))
    assert not at.exception
    assert paths["/api/v1/postings"] == 1
    assert paths["/api/v1/company-trends"] == 1
    assert paths["/api/v1/companies/acme/composition"] == 1
    assert sum(paths.values()) <= 12, paths


def test_load_more_appends_one_page(seeded_api, monkeypatch):
    monkeypatch.setattr(app_module, "PAGE_SIZE", 2)
    paths = count_requests(seeded_api)
    at = run_app(ApiClient(seeded_api))
    assert len(postings_table(at)) == 2
    assert [b.label for b in at.button if b.key == "load_more"] == ["Load 2 more"]
    before = paths["/api/v1/postings"]
    at.button(key="load_more").click().run()
    assert not at.exception
    assert len(postings_table(at)) == 4  # acme has 4 open postings
    assert paths["/api/v1/postings"] == before + 1
    assert not [b for b in at.button if b.key == "load_more"]  # cursor exhausted


def test_filter_change_resets_rows(seeded_api):
    seen = record_queries(seeded_api)
    at = run_app(ApiClient(seeded_api))
    at.selectbox(key="role_family_filter").select("sales").run()
    assert sorted(postings_table(at)["title"]) == ["Account Executive", "Senior Account Executive"]
    postings_calls = [params for path, params in seen if path == "/api/v1/postings"]
    assert postings_calls[-1]["role_family"] == "sales"
    assert postings_calls[-1]["company"] == "acme"


def test_company_table_has_trends(seeded_api):
    at = run_app(ApiClient(seeded_api))
    table = frame_with(at, "open_trend")
    assert list(table["company"]) == ["acme", "beta"]
    assert any(len(cell) for cell in table["open_trend"])
    assert "nan" not in table["d_open_prev_week"].astype(str).str.lower().tolist()


def test_every_chart_cell_is_all_numeric(seeded_api):
    """Streamlit's chart columns turn a WHOLE cell into an error string ("...,675" plus
    "is not a number") when any element is None or NaN, so a gap must never reach one."""
    cells = chart_cells(run_app(ApiClient(seeded_api)))
    assert {"trend", "open_trend", "new_trend"} <= set(cells)  # both tabs' sparklines
    for name, column in cells.items():
        for cell in column:
            bad = [v for v in cell if not (isinstance(v, Real) and math.isfinite(v))]
            assert not bad, f"{name}: {list(cell)}"


def test_older_empty_run_shows_empty_info(seeded_api, migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        empty = pd.DataFrame(columns=[*SCORE_COLUMNS, "basis", "level"])
        run = save_signal_run(session, T0, T0, DetectorParams(), empty)
        session.commit()
        run_id = run.id
    engine.dispose()
    at = run_app(ApiClient(seeded_api))
    at.selectbox(key="run").select(str(run_id)).run()
    assert not at.exception
    assert "No alerts in this run with the current filters." in [i.value for i in at.info]


def test_runs_tab_lists_runs_and_health(seeded_api):
    at = run_app(ApiClient(seeded_api))
    runs = frame_with(at, "taxonomy_version")
    assert len(runs) == 1
    assert {m.label: m.value for m in at.metric}["API Status"] == "OK"


@pytest.fixture
def hostile_api(seeded_api, migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        evil = get_or_create_company(session, "greenhouse", "evil", T1)
        run = start_run(session, T1)
        posting = Posting(
            source="greenhouse", company="evil", external_id="1", title=HOSTILE_TITLE,
            location_raw="London, UK", department=None, url="https://x.io/evil/1",
            first_published=T1 - timedelta(days=1), updated_at=None, fetched_at=T1,
        )  # fmt: skip
        record_snapshot(session, run, evil, [posting], T1)
        finish_run(session, run, T1)
        # ingestion already rejects non-http(s) URLs (models.Posting); write one straight
        # into the row, as an older version or another source could have, to prove the
        # dashboard's own guard (defence in depth)
        session.execute(
            update(PostingRecord)
            .where(PostingRecord.company_id == evil.id)
            .values(url="javascript:alert(1)")
        )
        session.commit()
    engine.dispose()
    return seeded_api


def test_scraped_text_never_rendered_as_markup(hostile_api):
    at = run_app(ApiClient(hostile_api))
    at.selectbox(key="company_view").select("evil").run()
    assert not at.exception
    table = postings_table(at)
    assert list(table["title"]) == [HOSTILE_TITLE]  # shown verbatim, as data
    assert table["url"].isna().all()  # javascript: link dropped
    rendered = [m.value for m in at.markdown] + [c.value for c in at.caption]
    assert not any("<script>" in v or "javascript:" in v for v in rendered)


def test_counter_helper_counts(seeded_api):
    paths: Counter = count_requests(seeded_api)
    seeded_api.get("/api/v1/health")
    assert paths == Counter({"/api/v1/health": 1})


class FailsOnNextPage(ApiClient):
    """The API goes away after the first postings page (e.g. key rotated, server down)."""

    def postings_page(self, **kwargs):
        if kwargs.get("cursor"):
            raise ApiUnavailable("Cannot reach the JobSignal API at http://testserver. x")
        return super().postings_page(**kwargs)


def test_load_more_failure_shows_error_not_exception(seeded_api, monkeypatch):
    monkeypatch.setattr(app_module, "PAGE_SIZE", 2)
    at = run_app(FailsOnNextPage(seeded_api))
    at.button(key="load_more").click().run()
    assert not at.exception
    assert [e.value for e in at.error] == ["Cannot reach the JobSignal API at http://testserver. x"]


def test_country_filter_offers_only_known_countries(seeded_api):
    seen = record_queries(seeded_api)
    at = run_app(ApiClient(seeded_api))
    country = at.selectbox(key="country_filter")
    assert list(country.options) == ["All", "GB", "US"]  # from the composition, no free text
    country.select("GB").run()
    assert not at.exception
    assert sorted(postings_table(at)["title"]) == ["Account Executive", "Senior Account Executive"]
    postings_calls = [params for path, params in seen if path == "/api/v1/postings"]
    assert postings_calls[-1]["country"] == "GB"


def test_refresh_now_reloads_postings(seeded_api, monkeypatch):
    monkeypatch.setattr(app_module, "PAGE_SIZE", 2)
    at = run_app(ApiClient(seeded_api))
    at.button(key="load_more").click().run()
    assert len(postings_table(at)) == 4
    at.button(key="refresh").click().run()
    assert not at.exception
    assert len(postings_table(at)) == 2  # loaded rows dropped with the cache: first page again
