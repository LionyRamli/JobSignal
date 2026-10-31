import json

from jobsignal.signals.params import LEVELS, SIGNALS_VERSION, UNKNOWN_COUNTRY, DetectorParams


def test_params_defaults_match_spec():
    p = DetectorParams()
    assert (p.baseline_weeks, p.volume_min_count, p.z_threshold, p.contraction_z_threshold) == (
        8,
        5,
        3.0,
        -3.0,
    )
    assert (p.contraction_min_baseline, p.strong_z, p.recent_weeks, p.mix_baseline_weeks) == (
        5.0,
        4.0,
        4,
        12,
    )
    assert (p.mix_min_recent, p.mix_min_company_baseline) == (5, 30)
    assert p.mix_flag_contractions is False  # fill-time bias (final review I4)
    assert SIGNALS_VERSION == "2026.11.1"
    assert LEVELS == ("company", "company_family", "company_country", "company_family_country")
    assert UNKNOWN_COUNTRY == "ZZ"


def test_params_json_round_trip():
    p = DetectorParams(baseline_weeks=6)
    assert DetectorParams(**json.loads(p.to_json())) == p
