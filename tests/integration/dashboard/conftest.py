"""Dashboard app fixtures: Streamlit's AppTest driving the real app against the real API."""

from collections import Counter

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.conftest import PROJECT_ROOT

APP = PROJECT_ROOT / "dashboard" / "app.py"


@pytest.fixture(autouse=True)
def _fresh_cache():
    """st.cache_data is process-global: one test's API answers must not leak into the next."""
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def run_app(client) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["api_client"] = client
    return at.run()


def count_requests(http_client) -> Counter:
    """Count requests by path on an httpx.Client (a FastAPI TestClient is one)."""
    paths: Counter = Counter()
    http_client.event_hooks["request"].append(lambda request: paths.update([request.url.path]))
    return paths


def texts(at: AppTest) -> list[str]:
    """Every rendered string value on the page (for 'never shown' assertions)."""
    found = []
    for kind in ("markdown", "text", "caption", "error", "warning", "info", "success",
                 "title", "header", "subheader", "metric", "json", "code"):  # fmt: skip
        for element in getattr(at, kind, []):
            found.append(str(getattr(element, "value", "")))
            found.append(str(getattr(element, "label", "")))
    for frame in at.dataframe:
        found.append(frame.value.to_string())
    return found
