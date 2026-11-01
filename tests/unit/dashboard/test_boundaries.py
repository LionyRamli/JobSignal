"""Assembly invariants: the dashboard is an HTTP client only, and never renders raw HTML."""

import subprocess
import sys

from tests.conftest import PROJECT_ROOT

FORBIDDEN = ("sqlalchemy", "jobsignal.storage", "jobsignal.signals", "jobsignal.api.routes")


def test_dashboard_does_not_load_the_database_layer():
    probe = (
        "import sys, jobsignal.dashboard.app\n"
        f"bad = sorted(m for m in sys.modules if m.startswith({FORBIDDEN!r}))\n"
        "print(bad)\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and literal code
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=120
    )
    assert result.stdout.strip() == "[]", result.stdout


def dashboard_sources():
    yield PROJECT_ROOT / "dashboard" / "app.py"
    yield from sorted((PROJECT_ROOT / "src" / "jobsignal" / "dashboard").glob("*.py"))


def test_no_unsafe_html_in_dashboard_source():
    sources = list(dashboard_sources())
    assert len(sources) >= 6
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "unsafe_allow_html" not in text, path
        assert "components.html" not in text, path
        assert "st.html" not in text, path


def test_no_deprecated_streamlit_width_argument():
    """use_container_width is past its removal date; width="stretch" replaces it."""
    for path in dashboard_sources():
        assert "use_container_width" not in path.read_text(encoding="utf-8"), path
