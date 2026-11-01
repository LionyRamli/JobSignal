"""The dashboard's plain-language layer, in English and Traditional Chinese.

Every code has a business name, every column a tooltip, and both languages say the same
things: same keys, same {placeholders}, nothing left untranslated.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import fields
from string import Formatter

import pytest

from jobsignal.dashboard import glossary as g
from jobsignal.dashboard.alerts import ALERT_COLUMNS, alerts_frame, display_alerts, group_alerts
from jobsignal.dashboard.trends import COMPANY_COLUMNS
from jobsignal.harmonization.taxonomy import RoleFamily, Seniority
from jobsignal.signals.params import LEVELS
from jobsignal.storage.schema import (
    LOCATION_KINDS,
    SIGNAL_DETECTORS,
    SIGNAL_STATUSES,
    SNAPSHOT_STATUSES,
)
from tests.unit.dashboard.test_alerts import mix, signal

CODE = re.compile(r"\b[a-z]+_[a-z_]+\b")  # snake_case: a raw code leaking into the UI
CJK = re.compile(r"[一-鿿]")
JARGON = re.compile(r"survivorship|scrape|\|z\||baseline", re.IGNORECASE)
NOT_WORDS = {"date_format", "datetime_format", "week_axis", "lang"}  # formats, not copy
COPIES = [g.EN, g.ZH]


def strings(copy: g.Copy) -> Iterator[str]:
    """Every user-facing string in one language (placeholders removed)."""
    for f in fields(copy):
        if f.name in NOT_WORDS:
            continue
        value = getattr(copy, f.name)
        values = value.values() if isinstance(value, Mapping) else [value]
        for item in values:
            for text in item if isinstance(item, g.Term) else [item]:
                if text:
                    yield re.sub(r"\{[^}]*\}", "", text)


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name}


def test_business_names_requested_by_the_user():
    assert g.EN.alert_table["z"].label == "Anomaly Score (Z)"
    assert g.EN.alert_table["direction"].label == "Trend (Expansion vs. Hiring Freeze)"
    assert g.EN.detector["mix_shift"] == "Strategic Focus Shift / Role Share"
    # volume flags drops too, so its label stays direction-neutral; the copy names it
    assert g.EN.detector["volume"] == "Total Hiring Volume"
    for text in (g.EN.guide, g.EN.controls["detector"].help, g.EN.alert_table["detector"].help):
        assert "Total Hiring Growth / Expansion" in text


def test_mandarin_business_names():
    assert g.ZH.alert_table["z"].label == "異常分數 (Z)"
    assert g.ZH.alert_table["direction"].label == "趨勢（擴張 vs. 招募凍結）"
    assert g.ZH.detector["mix_shift"] == "策略重心轉移／職務占比"
    assert g.ZH.detector["volume"] == "整體招募量"
    for text in (g.ZH.guide, g.ZH.controls["detector"].help, g.ZH.alert_table["detector"].help):
        assert "整體招募成長／擴張" in text


def test_both_languages_say_the_same_things():
    for f in fields(g.Copy):
        en, zh = getattr(g.EN, f.name), getattr(g.ZH, f.name)
        if isinstance(en, Mapping):
            assert set(en) == set(zh), f.name
            for key in en:
                if isinstance(en[key], str):
                    assert placeholders(en[key]) == placeholders(zh[key]), (f.name, key)
        elif isinstance(en, str):
            assert placeholders(en) == placeholders(zh), f.name


def test_mandarin_copy_is_mandarin():
    for text in strings(g.ZH):
        assert CJK.search(text), text


def test_english_copy_has_no_mandarin():
    for text in strings(g.EN):
        assert not CJK.search(text), text


@pytest.mark.parametrize("copy", COPIES, ids=["en", "zh"])
def test_every_code_the_api_can_send_has_a_name(copy):
    assert set(copy.detector) == set(SIGNAL_DETECTORS)
    assert set(copy.level) == set(LEVELS)
    assert set(copy.direction) == {"expansion", "contraction"}
    assert set(copy.band) == {"red", "yellow", "none"}
    assert set(copy.score_status) == set(SIGNAL_STATUSES)
    assert set(copy.snapshot_status) == set(SNAPSHOT_STATUSES)
    assert set(copy.health) == {"ok", "schema_missing"}
    for code in [*RoleFamily, *Seniority, *LOCATION_KINDS]:
        assert code in copy.codes, code
        assert not CODE.search(copy.pretty(code)), code


@pytest.mark.parametrize("copy", COPIES, ids=["en", "zh"])
def test_every_table_column_has_a_label_and_tooltip(copy):
    assert list(copy.alert_table) == ALERT_COLUMNS
    assert list(copy.company_table) == COMPANY_COLUMNS
    for table in (copy.alert_table, copy.company_table, copy.postings_table, copy.runs_table):
        for name, term in table.items():
            assert term.label, name
            assert term.help, name


@pytest.mark.parametrize("copy", COPIES, ids=["en", "zh"])
def test_no_raw_codes_in_any_ui_copy(copy):
    for text in strings(copy):
        assert not CODE.search(text), text


def test_on_screen_messages_avoid_jargon():
    for text in strings(g.EN):
        assert not JARGON.search(text), text


@pytest.mark.parametrize(
    ("copy", "code", "expected"),
    [
        (g.EN, "solutions_engineering", "Solutions Engineering"),
        (g.EN, "ml_research", "ML Research"),
        (g.EN, "staff_plus", "Staff+"),
        (g.EN, "director_plus", "Director+"),
        (g.EN, "sales", "Sales"),
        (g.EN, "some_new_family", "Some New Family"),  # future code: readable, not raw
        (g.EN, None, "—"),
        (g.ZH, "sales", "業務"),
        (g.ZH, "solutions_engineering", "解決方案工程"),
        (g.ZH, "remote", "遠端"),
        (g.ZH, None, "—"),
    ],
)
def test_pretty(copy, code, expected):
    assert copy.pretty(code) == expected


def test_copy_for_falls_back_to_english():
    assert g.copy_for("zh-Hant") is g.ZH
    assert g.copy_for("en") is g.EN
    assert g.copy_for("xx") is g.EN
    assert g.copy_for(None) is g.EN
    assert list(g.LANGUAGES) == ["en", "zh-Hant"]


def test_display_alerts_speaks_business():
    groups = group_alerts([signal(id=1, z=6.2), mix(id=2, z=-3.4, direction="contraction")])
    shown = display_alerts(alerts_frame(groups, {})).set_index("id")
    assert shown.loc[1, "band"] == "Extreme"
    assert shown.loc[1, "detector"] == "Total Hiring Volume"
    assert shown.loc[1, "direction"] == "▲ Expansion"
    assert shown.loc[2, "band"] == "Unusual"
    assert shown.loc[2, "detector"] == "Strategic Focus Shift / Role Share"
    assert shown.loc[2, "direction"] == "▼ Contraction"
    assert shown.loc[1, "z"] == 6.2  # numbers untouched


def test_display_alerts_in_mandarin():
    groups = group_alerts([signal(id=1, z=6.2), mix(id=2, z=-3.4, direction="contraction")])
    shown = display_alerts(alerts_frame(groups, {}, g.ZH), g.ZH).set_index("id")
    assert shown.loc[1, "band"] == "極端"
    assert shown.loc[1, "detector"] == "整體招募量"
    assert shown.loc[1, "direction"] == "▲ 擴張"
    assert shown.loc[1, "cell"] == "業務 · GB"
    assert shown.loc[2, "direction"] == "▼ 收縮"
    assert shown.loc[1, "z"] == 6.2
