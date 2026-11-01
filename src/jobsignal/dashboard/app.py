"""JobSignal Terminal: hiring alerts for business users (Streamlit). Its only data source is
the read-only API.

Run with ``uv run python scripts/run_dashboard.py`` (binds 127.0.0.1; light and dark themes
from ``.streamlit/config.toml``, switched in Streamlit's ⋮ menu). Tests inject an ApiClient
through ``st.session_state["api_client"]``.

Every API read goes through ``_cached`` (60 s TTL), so a new pipeline run shows up within a
minute and reruns caused by widget clicks cost no requests. Scraped text is rendered only
via st.dataframe / st.text, and links only for http(s) URLs. Every word on screen comes from
``glossary`` in the language picked in the sidebar (English or 繁體中文; ``?lang=`` in the
URL keeps it across reloads): every filter, number, column and chart explains itself.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any

import pandas as pd
import streamlit as st

from jobsignal.dashboard import glossary as g
from jobsignal.dashboard.alerts import (
    AlertGroup,
    alerts_frame,
    cell_label,
    describe,
    display_alerts,
    group_alerts,
    safe_url,
    stale_companies,
)
from jobsignal.dashboard.charts import composition_chart, trend_chart, z_chart
from jobsignal.dashboard.client import ApiClient, ApiError, make_client
from jobsignal.dashboard.trends import company_frame, previous_week_run

CACHE_TTL_SECONDS = 60
PAGE_SIZE = 200  # postings per page; more only on a click
COMPANY_TREND_WEEKS = 12
SIGNALS_LIMIT = 500
MAX_TREND_ROWS = 50  # trends are recomputed server-side (~0.1 s each): top groups only
ALL = "All"  # filter value for "no filter"; shown in the user's language
DETECT_COMMAND = "uv run python scripts/run_detect.py"
SCRAPE_COMMAND = "uv run python scripts/run_scrape.py <tokens>"
KPI_IDS = ("alerts", "expansions", "contractions", "companies")
# More expansions read green, more contractions read red; totals are neither good nor bad.
KPI_STYLE = {
    "alerts": ("off", ":material/notifications_active:"),
    "expansions": ("normal", ":material/trending_up:"),
    "contractions": ("inverse", ":material/trending_down:"),
    "companies": ("off", ":material/domain:"),
}

Column = st.column_config
SPARKLINE = partial(Column.LineChartColumn, color="auto")  # green if rising, red if falling


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _cached(_client: ApiClient, base_url: str, method: str, *args: Any, **kwargs: Any) -> Any:
    """One cached API read; the key is the base URL plus the call (the client is unhashed)."""
    return getattr(_client, method)(*args, **kwargs)


@st.cache_resource
def _default_client() -> ApiClient:
    return make_client()


@dataclass(frozen=True)
class Filters:
    run: str
    detector: str | None
    direction: str | None
    level: str | None
    company: str | None
    min_abs_z: float | None
    signals_only: bool

    def query(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "direction": self.direction,
            "level": self.level,
            "company": self.company,
            "min_abs_z": self.min_abs_z,
            "signals_only": self.signals_only,
            "limit": SIGNALS_LIMIT,
        }


class Api:
    """Cached calls bound to one client."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def __getattr__(self, method: str):
        def call(*args: Any, **kwargs: Any) -> Any:
            return _cached(self.client, self.client.base_url, method, *args, **kwargs)

        return call


def _choice(value: str) -> str | None:
    return None if value == ALL else value


def _named(copy: g.Copy, names: Mapping[str, str] | Callable[[str], str]) -> Callable[[str], str]:
    """format_func for a filter: show the business name, keep the code as the value."""
    lookup = names if callable(names) else (lambda code: names.get(code, code))
    return lambda code: copy.text["all"] if code == ALL else lookup(code)


def _control(copy: g.Copy, key: str, **format_args: Any) -> dict[str, Any]:
    """label/help/key for a widget, in the user's language."""
    term = copy.controls[key]
    return {"label": term.label.format(**format_args), "help": term.help, "key": key}


def _columns(table: Mapping[str, g.Term], shown: Iterable[str], **kinds) -> dict:
    """column_config for a table: every shown column gets its business label and tooltip."""
    return {
        name: kinds.get(name, Column.Column)(table[name].label, help=table[name].help)
        for name in shown
    }


def _chosen_language() -> g.Copy:
    """The user's language: this session's pick, else ``?lang=`` from the URL, else English."""
    if "lang" not in st.session_state:
        asked = st.query_params.get("lang")
        st.session_state["lang"] = asked if asked in g.LANGUAGES else "en"
    return g.copy_for(st.session_state["lang"])


def _language_switch(copy: g.Copy) -> None:
    with st.sidebar:
        st.selectbox(g.LANGUAGE_LABEL, list(g.LANGUAGES), format_func=g.LANGUAGES.get,
                     key="lang", help=copy.text["language_help"])  # fmt: skip
        st.caption(copy.text["theme_hint"])
    if st.query_params.get("lang") != copy.lang:
        st.query_params["lang"] = copy.lang  # a reload or a shared link keeps the language


def _sidebar(copy: g.Copy, runs, companies, meta) -> Filters:
    with st.sidebar:
        st.header(copy.text["sidebar_header"])
        st.caption(copy.text["sidebar_hint"])
        if st.button(**_control(copy, "refresh"), icon=":material/refresh:"):
            st.cache_data.clear()
            st.session_state.pop("postings", None)  # loaded rows are stale too
            st.rerun()
        labels = {"latest": copy.text["latest_run"]}
        labels |= {
            str(r.id): copy.text["run_option"].format(id=r.id, asof=f"{r.as_of:%Y-%m-%d %H:%M}")
            for r in runs
        }
        run = st.selectbox(options=list(labels), format_func=labels.get, **_control(copy, "run"))
        detector = st.selectbox(options=[ALL, *meta.detectors],
                                format_func=_named(copy, copy.detector),
                                **_control(copy, "detector"))  # fmt: skip
        direction = st.selectbox(options=[ALL, "expansion", "contraction"],
                                 format_func=_named(copy, copy.direction),
                                 **_control(copy, "direction"))  # fmt: skip
        level = st.selectbox(options=[ALL, *meta.signal_levels],
                             format_func=_named(copy, copy.level),
                             **_control(copy, "level"))  # fmt: skip
        company = st.selectbox(options=[ALL, *(c.board_token for c in companies)],
                               format_func=_named(copy, str),
                               **_control(copy, "company_filter"))  # fmt: skip
        min_abs_z = st.slider(min_value=0.0, max_value=10.0, value=0.0, step=0.5,
                              **_control(copy, "min_abs_z"))  # fmt: skip
        include = st.checkbox(**_control(copy, "include_all"))
    return Filters(
        run=run,
        detector=_choice(detector),
        direction=_choice(direction),
        level=_choice(level),
        company=_choice(company),
        min_abs_z=min_abs_z or None,
        signals_only=not include,
    )


def _kpis(groups: list[AlertGroup]) -> dict[str, int]:
    alerts = [group.headline for group in groups if group.headline.is_signal]
    return {
        "alerts": len(alerts),
        "expansions": sum(s.direction == "expansion" for s in alerts),
        "contractions": sum(s.direction == "contraction" for s in alerts),
        "companies": len({s.company for s in alerts}),
    }


def _kpi_row(copy: g.Copy, now: dict[str, int], before: dict[str, int] | None) -> None:
    for column, kpi in zip(st.columns(4), KPI_IDS, strict=True):
        delta_color, icon = KPI_STYLE[kpi]
        term = copy.kpis[kpi]
        column.metric(
            term.label, now[kpi], delta=None if before is None else now[kpi] - before[kpi],
            delta_color=delta_color,
            delta_description=None if before is None else copy.text["vs_last_week"],
            icon=icon, help=term.help, border=True,
        )  # fmt: skip


def _locations(posting, copy: g.Copy) -> str:
    return ", ".join(
        loc.city or loc.region_code or loc.country_code or copy.pretty(loc.kind)
        for loc in posting.locations
    )


def _postings_columns(copy: g.Copy, frame: pd.DataFrame) -> dict:
    return _columns(
        copy.postings_table, frame.columns,
        url=partial(Column.LinkColumn, display_text=copy.text["open_job_ad"]),
        first_seen_at=partial(Column.DatetimeColumn, format=copy.date_format),
    )  # fmt: skip


def _alert_detail(copy: g.Copy, api: Api, signal_id: int, trend) -> None:
    detail = api.signal(signal_id)
    signal = detail.signal
    st.text(describe(signal, copy))
    if signal.provisional:
        st.warning(copy.text["provisional"], icon=":material/info:")
    if trend is not None:
        st.altair_chart(trend_chart(trend, signal, copy), width="stretch")
        st.caption(copy.chart_help["trend_chart"])
        if all(p.z is None for p in trend.points):
            st.caption(copy.text["not_enough_history"])
    st.markdown(copy.text["postings_behind"])
    postings = pd.DataFrame(
        {
            "title": [p.title for p in detail.postings],
            "locations": [_locations(p, copy) for p in detail.postings],
            "url": [safe_url(p.url) for p in detail.postings],
        },
        dtype=object,
    )
    st.dataframe(postings, hide_index=True, column_config=_postings_columns(copy, postings))
    with st.expander(copy.text["technical_details"]):
        st.json(detail.run.params)


def _inspect_option(copy: g.Copy, s) -> str:
    score = copy.text["score_na"] if s.z is None else copy.text["score"].format(z=f"{s.z:+.2f}")
    direction = copy.direction.get(s.direction, copy.text["no_signal"])
    return f"#{s.id} {s.company} · {cell_label(s, copy)} · {direction} · {score}"


def _alerts_tab(copy: g.Copy, api: Api, runs, filters: Filters) -> None:
    text = copy.text
    if not runs:
        st.info(text["no_runs"].format(command=DETECT_COMMAND))
        return
    page = api.signals(filters.run, **filters.query())
    run = page.run
    if run is None:
        st.info(text["no_runs"].format(command=DETECT_COMMAND))
        return
    st.caption(
        text["run_caption"].format(
            id=run.id, asof=f"{run.as_of:%Y-%m-%d %H:%M}",
            taxonomy=run.taxonomy_version, signals=run.signals_version,
        )
    )  # fmt: skip
    groups = group_alerts(page.items)
    previous = previous_week_run(runs, run)
    before = (
        _kpis(group_alerts(api.signals(previous.id, **filters.query()).items))
        if (previous is not None)
        else None
    )
    _kpi_row(copy, _kpis(groups), before)
    if not groups:
        st.info(text["empty_run"])
        return
    shown = [group.headline.id for group in groups[:MAX_TREND_ROWS]]
    trends = {t.signal_id: t for t in api.signal_trends(tuple(shown))}
    frame = alerts_frame(groups, trends, copy)
    st.subheader(text["alert_ranking"])
    if len(page.items) == SIGNALS_LIMIT:
        st.caption(text["top_scores"].format(limit=SIGNALS_LIMIT))
    if len(groups) > MAX_TREND_ROWS:
        st.caption(text["trends_limited"].format(limit=MAX_TREND_ROWS))
    st.altair_chart(z_chart(frame, copy), width="stretch")
    st.caption(copy.chart_help["z_chart"])
    st.subheader(text["all_alerts"])
    st.caption(text["table_hint"])
    st.dataframe(
        display_alerts(frame, copy),
        hide_index=True,
        column_config=_columns(
            copy.alert_table, frame.columns,
            trend=SPARKLINE,
            z=partial(Column.NumberColumn, format="%+.2f"),
            dz_prev_week=partial(Column.NumberColumn, format="%+.2f"),
            d_baseline=partial(Column.NumberColumn, format="%+.1f"),
            week=partial(Column.DateColumn, format=copy.date_format),
            provisional=Column.CheckboxColumn,
        ),
    )  # fmt: skip
    st.subheader(text["inspect_alert"])
    by_id = {group.headline.id: group.headline for group in groups}
    selected = st.selectbox(options=list(by_id),
                            format_func=lambda i: _inspect_option(copy, by_id[i]),
                            **_control(copy, "inspect"))  # fmt: skip
    _alert_detail(copy, api, selected, trends.get(selected))


def _postings_section(copy: g.Copy, api: Api, company: str, meta, countries: list[str]) -> None:
    left, middle, right = st.columns(3)
    family = left.selectbox(options=[ALL, *meta.role_families],
                            format_func=_named(copy, copy.pretty),
                            **_control(copy, "role_family_filter"))  # fmt: skip
    seniority = middle.selectbox(options=[ALL, *meta.seniorities],
                                 format_func=_named(copy, copy.pretty),
                                 **_control(copy, "seniority_filter"))  # fmt: skip
    # options come from the company's own composition: no free text, no invalid code
    country = right.selectbox(options=[ALL, *countries], format_func=_named(copy, str),
                              **_control(copy, "country_filter"))  # fmt: skip
    query = {
        "company": company,
        "role_family": _choice(family),
        "seniority": _choice(seniority),
        "country": _choice(country),
    }
    key = tuple(query.values())
    state = st.session_state.get("postings")
    if state is None or state["key"] != key:  # new filter set: start over with one page
        page = api.postings_page(**query, limit=PAGE_SIZE)
        state = {"key": key, "rows": list(page.items), "cursor": page.next_cursor}
        st.session_state["postings"] = state
    rows = state["rows"]
    more = copy.text["more_available"] if state["cursor"] else ""
    st.caption(copy.text["showing_postings"].format(count=len(rows), more=more))
    frame = pd.DataFrame(
        {
            "title": [p.title for p in rows],
            "role_family": [copy.pretty(p.role_family) for p in rows],
            "seniority": [copy.pretty(p.seniority) for p in rows],
            "locations": [_locations(p, copy) for p in rows],
            "first_seen_at": [p.first_seen_at for p in rows],
            "url": [safe_url(p.url) for p in rows],
        },
        dtype=object,
    )
    st.dataframe(frame, hide_index=True, column_config=_postings_columns(copy, frame))
    # handled in the script body (not an on_click callback) so an API failure reaches
    # main()'s ApiError handler: callbacks run before the body, outside that try
    if state["cursor"] and st.button(**_control(copy, "load_more", count=PAGE_SIZE)):
        page = api.postings_page(**query, limit=PAGE_SIZE, cursor=state["cursor"])
        state["rows"] = [*state["rows"], *page.items]  # exactly ONE more page per click
        state["cursor"] = page.next_cursor
        st.rerun()


def _companies_tab(copy: g.Copy, api: Api, companies, meta) -> None:
    text = copy.text
    if not companies:
        st.info(text["no_companies"].format(command=SCRAPE_COMMAND))
        return
    trends = api.company_trends(weeks=COMPANY_TREND_WEEKS)
    st.subheader(text["company_overview"])
    st.caption(f"{text['company_overview_caption']} {text['table_hint']}")
    frame = company_frame(companies, trends, datetime.now(UTC))
    frame["status"] = [copy.snapshot_status.get(s, s) if s else s for s in frame["status"]]
    st.dataframe(
        frame,
        hide_index=True,
        column_config=_columns(
            copy.company_table, frame.columns,
            open_trend=SPARKLINE,
            new_trend=SPARKLINE,
            d_open_prev_week=partial(Column.NumberColumn, format="%+d"),
            last_scrape=partial(Column.DatetimeColumn, format=copy.datetime_format),
            stale=Column.CheckboxColumn,
        ),
    )  # fmt: skip
    st.subheader(text["company_deep_dive"])
    company = st.selectbox(options=[c.board_token for c in companies],
                           **_control(copy, "company_view"))  # fmt: skip
    composition = api.composition(company)
    open_roles = copy.kpis["open_roles"]
    st.metric(open_roles.label, composition.open_postings, icon=":material/work:",
              help=open_roles.help, border=True)  # fmt: skip
    for column, (counts, dimension, name) in zip(
        st.columns(3),
        [
            (composition.by_role_family, copy.postings_table["role_family"].label, copy.pretty),
            (composition.by_seniority, copy.postings_table["seniority"].label, copy.pretty),
            (composition.by_country, copy.controls["country_filter"].label, str),
        ],
        strict=True,
    ):
        chart = composition_chart(counts, dimension, name, copy)
        column.altair_chart(chart, width="stretch")
    st.caption(copy.chart_help["composition"])
    st.subheader(text["job_postings"])
    countries = sorted(c.key for c in composition.by_country if c.key)
    _postings_section(copy, api, company, meta, countries)


def _runs_tab(copy: g.Copy, api: Api, runs, filters: Filters) -> None:
    health = api.health()
    left, middle, right = st.columns(3)
    for column, kpi, value, icon in (
        (left, "api_status", copy.health.get(health.status, health.status),
         ":material/monitor_heart:"),
        (middle, "taxonomy", health.taxonomy_version, ":material/category:"),
        (right, "signals", health.signals_version, ":material/rule:"),
    ):  # fmt: skip
        term = copy.kpis[kpi]
        column.metric(term.label, value, icon=icon, help=term.help, border=True)
    if not runs:
        st.info(copy.text["no_runs"].format(command=DETECT_COMMAND))
        return
    st.subheader(copy.text["analysis_runs"])
    frame = pd.DataFrame(
        {
            "id": [r.id for r in runs],
            "as_of": [r.as_of for r in runs],
            "computed_at": [r.computed_at for r in runs],
            "signals_version": [r.signals_version for r in runs],
            "taxonomy_version": [r.taxonomy_version for r in runs],
        }
    )
    st.dataframe(frame, hide_index=True, column_config=_columns(copy.runs_table, frame.columns))
    selected = (
        runs[0]
        if filters.run == "latest"
        else next((r for r in runs if str(r.id) == filters.run), runs[0])
    )
    st.caption(copy.text["run_params"].format(id=selected.id))
    st.json(selected.params)


def _render(copy: g.Copy, client: ApiClient) -> None:
    api = Api(client)
    # first reads happen before any filter widget: an unreachable API renders only the error
    runs = api.signal_runs()
    companies = api.companies()
    meta = api.meta()
    filters = _sidebar(copy, runs, companies, meta)
    stale = stale_companies(companies, datetime.now(UTC))
    if stale:
        st.warning(copy.text["stale"].format(companies=", ".join(stale)),
                   icon=":material/schedule:")  # fmt: skip
    with st.expander(copy.guide_title, icon=":material/help:"):
        st.markdown(copy.guide)
    alerts, companies_tab, runs_tab = st.tabs(
        [f":material/bolt: {copy.text['tab_alerts']}",
         f":material/apartment: {copy.text['tab_companies']}",
         f":material/monitor_heart: {copy.text['tab_runs']}"]
    )  # fmt: skip
    with alerts:
        _alerts_tab(copy, api, runs, filters)
    with companies_tab:
        _companies_tab(copy, api, companies, meta)
    with runs_tab:
        _runs_tab(copy, api, runs, filters)


def main() -> None:
    copy = _chosen_language()
    st.set_page_config(page_title=copy.text["title"], page_icon=":material/insights:",
                       layout="wide")  # fmt: skip
    _language_switch(copy)
    st.title(copy.text["title"])
    st.caption(copy.text["tagline"])
    client = st.session_state.get("api_client") or _default_client()
    try:
        _render(copy, client)
    except ApiError as err:
        st.error(copy.error_prefix + str(err))
        st.stop()
