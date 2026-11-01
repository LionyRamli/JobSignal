"""Every control, number, column and chart explains itself, in English or Traditional Chinese."""

import json
import re

import httpx
import pytest

from jobsignal.dashboard import glossary as g
from jobsignal.dashboard.client import ApiClient
from tests.integration.dashboard.conftest import run_app

pytestmark = pytest.mark.integration

CJK = re.compile(r"[一-鿿]")
WIDGETS = ("selectbox", "slider", "checkbox", "button")


@pytest.fixture
def at(seeded_api):
    app = run_app(ApiClient(seeded_api))
    assert not app.exception
    return app


@pytest.fixture
def zh(at):
    at.selectbox(key="lang").select("zh-Hant").run()
    assert not at.exception
    return at


def controls(at) -> list:
    return [c for kind in WIDGETS for c in getattr(at, kind)]


def column_terms(at) -> list[tuple[str, str, str]]:
    """(column, label, tooltip) for every column of every table on the page."""
    found = []
    for frame in at.dataframe:
        config = json.loads(frame.proto.columns or "{}")
        for column in frame.value.columns:
            found.append((column, config[column].get("label"), config[column].get("help")))
    return found


def ui_words(at) -> list[str]:
    """Every piece of interface text: everything except data (names, titles, numbers)."""
    words = [at.title[0].value]
    for kind in ("header", "subheader", "caption", "markdown", "info", "warning", "error", "text"):
        words += [e.value for e in getattr(at, kind)]
    words += [t.label for t in at.tabs] + [e.label for e in at.expander]
    words += [part for m in at.metric for part in (m.label, m.help)]
    words += [part for c in controls(at) if c.key != "lang" for part in (c.label, c.help)]
    words += [part for _, label, tip in column_terms(at) for part in (label, tip)]
    return [w for w in words if w]


def test_every_control_has_a_tooltip(at):
    assert len(controls(at)) >= 13  # language, sidebar filters, inspect, company, postings
    for control in controls(at):
        assert control.help, control.key or control.label


def test_filters_use_the_business_names(at):
    labels = {key: at.selectbox(key=key).label for key in ("detector", "direction")}
    assert labels == {"detector": "Signal Type", "direction": g.EN.alert_table["direction"].label}
    assert at.slider(key="min_abs_z").label == "Minimum Anomaly Score (Z)"


def test_every_kpi_tile_has_a_tooltip(at):
    assert len(at.metric) >= 8  # 4 alert KPIs, open roles, 3 health tiles
    for metric in at.metric:
        assert metric.help, metric.label


def test_every_table_column_has_a_business_label_and_tooltip(at):
    assert len(at.dataframe) >= 4  # alerts, companies, postings, runs
    for column, label, tip in column_terms(at):
        assert label, column
        assert tip, column


def test_every_chart_is_explained(at):
    captions = {c.value for c in at.caption}
    for chart in ("z_chart", "trend_chart", "composition"):
        assert g.EN.chart_help[chart] in captions, chart


def test_first_time_user_guide(at):
    assert g.EN.guide_title in [e.label for e in at.expander]
    assert g.EN.guide in [m.value for m in at.markdown]


def test_sidebar_explains_the_light_dark_switch(at):
    assert g.EN.text["theme_hint"] in [c.value for c in at.sidebar.caption]


def test_language_switch_offers_both_languages(at):
    lang = at.selectbox(key="lang")
    assert lang.label == "Language / 語言"
    assert lang.options == ["English", "繁體中文"]
    assert lang.help


def test_english_page_has_no_mandarin_but_the_switch(at):
    for word in ui_words(at):
        assert not CJK.search(word), word


def test_mandarin_translates_every_word(zh):
    words = ui_words(zh)
    assert len(words) > 120
    for word in words:
        assert CJK.search(word), word


def test_mandarin_names_the_key_numbers(zh):
    assert zh.title[0].value == g.ZH.text["title"]
    assert [m.label for m in zh.metric][:4] == [
        g.ZH.kpis[k].label for k in ("alerts", "expansions", "contractions", "companies")
    ]
    terms = {column: label for column, label, _ in column_terms(zh)}
    assert terms["z"] == "異常分數 (Z)"
    assert terms["direction"] == "趨勢（擴張 vs. 招募凍結）"
    assert zh.selectbox(key="direction").label == "趨勢（擴張 vs. 招募凍結）"


def test_mandarin_translates_table_values_not_data(zh):
    alerts = next(f.value for f in zh.dataframe if "band" in f.value.columns)
    assert set(alerts["band"]) <= set(g.ZH.band.values())
    assert set(alerts["direction"]) <= set(g.ZH.direction.values())
    assert set(alerts["detector"]) <= set(g.ZH.detector.values())
    assert set(alerts["company"]) == {"acme"}  # data stays as scraped


def test_language_choice_survives_a_reload_via_the_url(seeded_api):
    at = run_app(ApiClient(seeded_api))
    at.selectbox(key="lang").select("zh-Hant").run()
    assert at.query_params["lang"] == "zh-Hant"
    fresh = run_app(ApiClient(seeded_api), query_params={"lang": "zh-Hant"})
    assert fresh.selectbox(key="lang").value == "zh-Hant"
    assert fresh.title[0].value == g.ZH.text["title"]


def test_unknown_language_in_the_url_falls_back_to_english(seeded_api):
    at = run_app(ApiClient(seeded_api), query_params={"lang": "xx"})
    assert not at.exception
    assert at.title[0].value == g.EN.text["title"]


def test_api_down_is_explained_in_mandarin():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://127.0.0.1:9")
    at = run_app(ApiClient(client), query_params={"lang": "zh-Hant"})
    assert len(at.error) == 1
    assert at.error[0].value.startswith(g.ZH.error_prefix)
    assert not at.exception
