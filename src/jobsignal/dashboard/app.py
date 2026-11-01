"""JobSignal alerting dashboard (Streamlit). Its only data source is the read-only API.

Run with ``uv run python scripts/run_dashboard.py`` (binds 127.0.0.1). Tests inject an
ApiClient through ``st.session_state["api_client"]``.

Every API read goes through ``_cached`` (60 s TTL), so a new pipeline run shows up within a
minute and reruns caused by widget clicks cost no requests. Scraped text is rendered only
via st.dataframe / st.text, and links only for http(s) URLs.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import streamlit as st

from jobsignal.dashboard.alerts import (
    AlertGroup,
    alerts_frame,
    cell_label,
    describe,
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
ALL = "All"
NO_RUNS = "No signal runs yet. Run: uv run python scripts/run_detect.py"
EMPTY_RUN = "No alerts in this run with the current filters."
PROVISIONAL = (
    "Provisional: published-date shares are survivorship-biased. Treat as a lead, not evidence."
)
NOT_ENOUGH_HISTORY = "Not enough history yet"
STALE = "Stale data: {tokens}. Last scrape is older than 36 h or did not finish ok."


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


def _sidebar(api: Api, runs, companies, meta) -> Filters:
    with st.sidebar:
        st.header("Filters")
        if st.button("Refresh now"):
            st.cache_data.clear()
            st.rerun()
        labels = {"latest": "Latest run"}
        labels |= {str(r.id): f"#{r.id} · as of {r.as_of:%Y-%m-%d %H:%M} UTC" for r in runs}
        run = st.selectbox("Run", list(labels), format_func=labels.get, key="run")
        detector = st.selectbox("Detector", [ALL, *meta.detectors], key="detector")
        direction = st.selectbox("Direction", [ALL, "expansion", "contraction"], key="direction")
        level = st.selectbox("Level", [ALL, *meta.signal_levels], key="level")
        company = st.selectbox(
            "Company", [ALL, *(c.board_token for c in companies)], key="company_filter"
        )
        min_abs_z = st.slider("Minimum |z|", 0.0, 10.0, 0.0, 0.5, key="min_abs_z")
        include = st.checkbox("Include non-alert scores", key="include_all")
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
    alerts = [g.headline for g in groups if g.headline.is_signal]
    return {
        "Alerts": len(alerts),
        "Expansions": sum(s.direction == "expansion" for s in alerts),
        "Contractions": sum(s.direction == "contraction" for s in alerts),
        "Companies with alerts": len({s.company for s in alerts}),
    }


def _postings_frame(postings) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "title": [p.title for p in postings],
            "locations": [_locations(p) for p in postings],
            "url": [safe_url(p.url) for p in postings],
        },
        dtype=object,
    )  # fmt: skip


def _alert_detail(api: Api, signal_id: int, trend) -> None:
    detail = api.signal(signal_id)
    signal = detail.signal
    st.text(describe(signal))
    if signal.provisional:
        st.warning(PROVISIONAL)
    if trend is not None:
        st.altair_chart(trend_chart(trend, signal), use_container_width=True)
        if all(p.z is None for p in trend.points):
            st.caption(NOT_ENOUGH_HISTORY)
    st.dataframe(
        _postings_frame(detail.postings),
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("url")},
    )
    with st.expander("Run parameters"):
        st.json(detail.run.params)


def _alerts_tab(api: Api, runs, filters: Filters) -> None:
    if not runs:
        st.info(NO_RUNS)
        return
    page = api.signals(filters.run, **filters.query())
    run = page.run
    if run is None:
        st.info(NO_RUNS)
        return
    st.caption(
        f"Run #{run.id} · as of {run.as_of:%Y-%m-%d %H:%M} UTC · "
        f"taxonomy {run.taxonomy_version} · signals {run.signals_version}"
    )
    groups = group_alerts(page.items)
    previous = previous_week_run(runs, run)
    before = (
        _kpis(group_alerts(api.signals(previous.id, **filters.query()).items))
        if (previous is not None)
        else None
    )
    for column, (label, value) in zip(st.columns(4), _kpis(groups).items(), strict=True):
        column.metric(label, value, delta=None if before is None else value - before[label])
    if not groups:
        st.info(EMPTY_RUN)
        return
    shown = [g.headline.id for g in groups[:MAX_TREND_ROWS]]
    trends = {t.signal_id: t for t in api.signal_trends(tuple(shown))}
    frame = alerts_frame(groups, trends)
    if len(page.items) == SIGNALS_LIMIT:
        st.caption(f"Showing the top {SIGNALS_LIMIT} scores by |z|.")
    if len(groups) > MAX_TREND_ROWS:
        st.caption(f"Trends shown for the top {MAX_TREND_ROWS} alerts.")
    st.altair_chart(z_chart(frame), use_container_width=True)
    st.dataframe(
        frame,
        hide_index=True,
        column_config={
            "trend": st.column_config.LineChartColumn("8-week trend"),
            "z": st.column_config.NumberColumn("z", format="%+.2f"),
            "dz_prev_week": st.column_config.NumberColumn("Δz vs prev week", format="%+.2f"),
            "d_baseline": st.column_config.NumberColumn("Δ vs baseline", format="%+.1f"),
        },
    )
    by_id = {g.headline.id: g.headline for g in groups}
    selected = st.selectbox(
        "Inspect alert",
        list(by_id),
        format_func=lambda i: (
            f"#{i} {by_id[i].company} · {cell_label(by_id[i])} · "
            f"{by_id[i].direction or 'no signal'} · "
            + ("z n/a" if by_id[i].z is None else f"z {by_id[i].z:+.2f}")
        ),
        key="inspect",
    )
    _alert_detail(api, selected, trends.get(selected))


def _locations(posting) -> str:
    return ", ".join(
        loc.city or loc.region_code or loc.country_code or loc.kind for loc in posting.locations
    )


def _load_more(api: Api, query: dict[str, Any]) -> None:
    """Button callback: fetch exactly ONE more page and append it (runs before the rerun)."""
    state = st.session_state["postings"]
    page = api.postings_page(**query, limit=PAGE_SIZE, cursor=state["cursor"])
    state["rows"] = [*state["rows"], *page.items]
    state["cursor"] = page.next_cursor


def _postings_section(api: Api, company: str, meta) -> None:
    left, middle, right = st.columns(3)
    family = left.selectbox("Role family", [ALL, *meta.role_families], key="role_family_filter")
    seniority = middle.selectbox("Seniority", [ALL, *meta.seniorities], key="seniority_filter")
    country = right.text_input("Country (ISO code)", key="country_filter").strip().upper()
    query = {
        "company": company,
        "role_family": _choice(family),
        "seniority": _choice(seniority),
        "country": country or None,
    }
    key = tuple(query.values())
    state = st.session_state.get("postings")
    if state is None or state["key"] != key:  # new filter set: start over with one page
        page = api.postings_page(**query, limit=PAGE_SIZE)
        state = {"key": key, "rows": list(page.items), "cursor": page.next_cursor}
        st.session_state["postings"] = state
    rows = state["rows"]
    more = " · more available" if state["cursor"] else ""
    st.caption(f"Showing {len(rows)} postings · sorting applies to loaded rows{more}")
    st.dataframe(
        pd.DataFrame(
            {
                "title": [p.title for p in rows],
                "role_family": [p.role_family for p in rows],
                "seniority": [p.seniority for p in rows],
                "locations": [_locations(p) for p in rows],
                "first_seen_at": [p.first_seen_at for p in rows],
                "url": [safe_url(p.url) for p in rows],
            },
            dtype=object,
        ),
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("url")},
    )
    if state["cursor"]:
        st.button(f"Load {PAGE_SIZE} more", key="load_more", on_click=_load_more, args=(api, query))


def _companies_tab(api: Api, companies, meta) -> None:
    if not companies:
        st.info("No companies scraped yet. Run: uv run python scripts/run_scrape.py <tokens>")
        return
    trends = api.company_trends(weeks=COMPANY_TREND_WEEKS)
    st.dataframe(
        company_frame(companies, trends, datetime.now(UTC)),
        hide_index=True,
        column_config={
            "open_trend": st.column_config.LineChartColumn("open postings (12 weeks)"),
            "new_trend": st.column_config.LineChartColumn("new postings (12 weeks)"),
            "d_open_prev_week": st.column_config.NumberColumn("Δ vs prev week", format="%+d"),
        },
    )
    company = st.selectbox("Company", [c.board_token for c in companies], key="company_view")
    composition = api.composition(company)
    st.caption(f"{composition.open_postings} open postings")
    for column, (counts, title) in zip(
        st.columns(3),
        [
            (composition.by_role_family, "Role family"),
            (composition.by_seniority, "Seniority"),
            (composition.by_country, "Country"),
        ],
        strict=True,
    ):
        column.altair_chart(composition_chart(counts, title), use_container_width=True)
    _postings_section(api, company, meta)


def _runs_tab(api: Api, runs, filters: Filters) -> None:
    health = api.health()
    left, middle, right = st.columns(3)
    left.metric("API", health.status)
    middle.metric("Taxonomy", health.taxonomy_version)
    right.metric("Signals", health.signals_version)
    if not runs:
        st.info(NO_RUNS)
        return
    st.dataframe(
        pd.DataFrame(
            {
                "id": [r.id for r in runs],
                "as_of": [r.as_of for r in runs],
                "computed_at": [r.computed_at for r in runs],
                "signals_version": [r.signals_version for r in runs],
                "taxonomy_version": [r.taxonomy_version for r in runs],
            }
        ),
        hide_index=True,
    )
    selected = (
        runs[0]
        if filters.run == "latest"
        else next((r for r in runs if str(r.id) == filters.run), runs[0])
    )
    st.caption(f"Parameters of run #{selected.id}")
    st.json(selected.params)


def _render(client: ApiClient) -> None:
    api = Api(client)
    # first reads happen before any widget: an unreachable API renders only the error
    runs = api.signal_runs()
    companies = api.companies()
    meta = api.meta()
    filters = _sidebar(api, runs, companies, meta)
    stale = stale_companies(companies, datetime.now(UTC))
    if stale:
        st.warning(STALE.format(tokens=", ".join(stale)))
    alerts, companies_tab, runs_tab = st.tabs(["Alerts", "Companies", "Runs & health"])
    with alerts:
        _alerts_tab(api, runs, filters)
    with companies_tab:
        _companies_tab(api, companies, meta)
    with runs_tab:
        _runs_tab(api, runs, filters)


def main() -> None:
    st.set_page_config(page_title="JobSignal", layout="wide")
    st.title("JobSignal · hiring alerts")
    client = st.session_state.get("api_client") or _default_client()
    try:
        _render(client)
    except ApiError as err:
        st.error(str(err))
        st.stop()
