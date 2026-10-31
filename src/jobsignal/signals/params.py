"""Detector parameters (spec defaults) and shared constants. Every run stores its params."""

import json
from dataclasses import asdict, dataclass

SIGNALS_VERSION = "2026.11.1"
LEVELS = ("company", "company_family", "company_country", "company_family_country")
UNKNOWN_COUNTRY = "ZZ"


@dataclass(frozen=True)
class DetectorParams:
    baseline_weeks: int = 8
    volume_min_count: int = 5
    z_threshold: float = 3.0
    contraction_z_threshold: float = -3.0
    contraction_min_baseline: float = 5.0
    strong_z: float = 4.0  # applied to |z|
    recent_weeks: int = 4
    mix_baseline_weeks: int = 12
    mix_min_recent: int = 5
    mix_min_company_baseline: int = 30

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)
