from fastapi import APIRouter

from jobsignal.api.schemas import Meta
from jobsignal.harmonization.locations import LocationKind
from jobsignal.harmonization.taxonomy import TAXONOMY_VERSION, RoleFamily, Seniority
from jobsignal.signals.params import LEVELS, SIGNALS_VERSION
from jobsignal.storage.schema import SIGNAL_DETECTORS

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=Meta)
def meta() -> Meta:
    """Vocabularies for dashboard filters."""
    return Meta(
        role_families=[f.value for f in RoleFamily],
        seniorities=[s.value for s in Seniority],
        location_kinds=[k.value for k in LocationKind],
        signal_levels=list(LEVELS),
        detectors=list(SIGNAL_DETECTORS),
        taxonomy_version=TAXONOMY_VERSION,
        signals_version=SIGNALS_VERSION,
    )
