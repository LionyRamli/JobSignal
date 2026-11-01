"""The two themes in .streamlit/config.toml: a dark trading terminal and a daylight mode.

Users switch in Streamlit's own menu (⋮ → System / Light / Dark). Charts take every colour
from the active theme's chart palette (``charts.SLOTS``), so each palette is checked
against its own page colour here.
"""

import tomllib

import pytest

from jobsignal.dashboard.charts import SLOTS
from tests.conftest import PROJECT_ROOT
from tests.unit.dashboard.contrast import contrast, luminance

MODES = ("light", "dark")
SHARED_ONLY = {"base", "font", "codeFont", "baseRadius", "buttonRadius", "showWidgetBorder",
               "showSidebarBorder", "metricValueFontSize", "metricValueFontWeight"}  # fmt: skip


def theme() -> dict:
    config = tomllib.loads(
        (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    )
    return config["theme"]


def test_both_modes_exist_so_the_menu_offers_the_switch():
    """Streamlit shows its Light / Dark picker only when there is more than one theme."""
    t = theme()
    assert set(MODES) <= set(t)
    assert "base" not in t  # a root base would pin both modes to one look
    colours = {k for k, v in t.items() if isinstance(v, str) and v.startswith("#")}
    assert not colours, colours  # every colour belongs to a mode


@pytest.mark.parametrize("mode", MODES)
def test_mode_is_legible(mode):
    m = theme()[mode]
    page = m["backgroundColor"]
    assert contrast(m["textColor"], page) >= 7  # WCAG AAA body text
    assert contrast(m["textColor"], m["secondaryBackgroundColor"]) >= 7
    for key in ("primaryColor", "linkColor", "greenTextColor", "redTextColor",
                "yellowTextColor", "blueTextColor"):  # fmt: skip
        assert contrast(m[key], page) >= 4.5, key
    sidebar = m["sidebar"]
    assert contrast(m["textColor"], sidebar["backgroundColor"]) >= 7


def test_dark_mode_is_the_trading_terminal():
    assert luminance(theme()["dark"]["backgroundColor"]) < 0.01  # near-black navy
    assert luminance(theme()["light"]["backgroundColor"]) > 0.9


@pytest.mark.parametrize("mode", MODES)
def test_chart_palette_reads_on_its_own_page(mode):
    m = theme()[mode]
    page = m["backgroundColor"]
    colours = dict(zip(SLOTS, m["chartCategoricalColors"], strict=True))
    for slot in ("extreme", "unusual", "series", "ink"):  # data and value labels
        assert contrast(colours[slot], page) >= 4.5, slot
    assert contrast(colours["below"], page) >= 3  # context-only bars: WCAG non-text
    assert contrast(colours["series"], colours["normal"]) >= 3  # line over its normal band
    assert 1.1 <= contrast(colours["normal"], page) < 2  # a quiet band, not a block


@pytest.mark.parametrize("mode", MODES)
def test_sparklines_and_deltas_use_mode_colours(mode):
    """LineChartColumn(color="auto") and st.metric deltas draw with green/red."""
    m = theme()[mode]
    for key in ("greenColor", "redColor"):
        assert contrast(m[key], m["backgroundColor"]) >= 3, key
