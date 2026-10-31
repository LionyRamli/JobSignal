import copy
from importlib.resources import files

import pytest

from jobsignal.harmonization.taxonomy import (
    SENIORITY_PRECEDENCE,
    TAXONOMY_VERSION,
    RoleFamily,
    Seniority,
    _build_taxonomy,
    _load_raw,
    load_taxonomy,
)


def test_enums_match_spec():
    assert TAXONOMY_VERSION == "2026.11.3"
    assert [f.value for f in RoleFamily] == [
        "software_engineering", "ml_research", "data", "solutions_engineering", "security",
        "product_management", "program_management", "design", "sales", "customer_success",
        "marketing", "operations", "finance", "legal", "people", "other",
    ]  # fmt: skip
    assert [s.value for s in Seniority] == [
        "intern", "entry", "mid", "senior", "staff_plus", "manager", "director_plus",
    ]  # fmt: skip


def test_precedence_is_spec_order():
    assert [s.value for s in SENIORITY_PRECEDENCE] == [
        "intern", "director_plus", "manager", "staff_plus", "senior", "entry", "mid",
    ]  # fmt: skip


def test_loads_shipped_data():
    taxonomy = load_taxonomy()
    assert taxonomy.family_phrases[RoleFamily.SOFTWARE_ENGINEERING]
    assert RoleFamily.OTHER not in taxonomy.family_phrases
    assert "product manager" in taxonomy.ic_manager_phrases
    assert taxonomy.countries["united states"] == "US"
    assert taxonomy.regions["california"] == "US-CA"


def test_loader_validates_unknown_family():
    raw = copy.deepcopy(_load_raw())
    raw["roles"]["families"]["astronaut"] = {"title": ["astronaut"]}
    with pytest.raises(ValueError, match="astronaut"):
        _build_taxonomy(raw)


@pytest.mark.parametrize("bad_code", ["usa", "US-", "us-ca", "U1", "US-CALIF"])
def test_loader_rejects_bad_iso_code(bad_code):
    raw = copy.deepcopy(_load_raw())
    raw["places"]["regions"][bad_code] = ["somewhere"]
    with pytest.raises(ValueError, match="ISO"):
        _build_taxonomy(raw)


def test_loader_rejects_duplicate_alias_across_tables():
    raw = copy.deepcopy(_load_raw())
    raw["places"]["countries"]["FR"].append("california")
    with pytest.raises(ValueError, match="california"):
        _build_taxonomy(raw)


def test_aliases_are_unique_and_lowercase():
    taxonomy = load_taxonomy()
    aliases = [
        *taxonomy.countries, *taxonomy.regions, *taxonomy.cities, *taxonomy.macro_regions,
    ]  # fmt: skip
    assert len(aliases) == len(set(aliases))
    assert all(a == a.lower() and a == a.strip() for a in aliases)


def test_every_us_state_present():
    us = {code for code in load_taxonomy().regions.values() if code.startswith("US-")}
    assert len(us) == 51  # 50 states + DC


def test_data_ships_in_wheel():
    names = {p.name for p in files("jobsignal.harmonization.data").iterdir()}
    assert {"roles.toml", "seniority.toml", "places.toml"} <= names


def test_data_files_are_not_gitignored():
    """An unanchored `data/` in .gitignore once hid these files from git and the wheel."""
    import subprocess

    from tests.conftest import PROJECT_ROOT

    data_dir = PROJECT_ROOT / "src" / "jobsignal" / "harmonization" / "data"
    paths = [str(p.relative_to(PROJECT_ROOT)) for p in data_dir.glob("*.toml")]
    assert len(paths) == 3
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "check-ignore", "--no-index", *paths],  # noqa: S607 - git on PATH in dev and CI
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, f"gitignored: {result.stdout}"


# Changing any rule file or classifier must change TAXONOMY_VERSION (stored results carry it,
# and only a version change makes `harmonize` reprocess). Update BOTH lines below together.
FINGERPRINTED_VERSION = "2026.11.3"
FINGERPRINT = "db07aec6ae896b2c"


def _fingerprint() -> str:
    import hashlib

    from tests.conftest import PROJECT_ROOT

    root = PROJECT_ROOT / "src" / "jobsignal" / "harmonization"
    paths = [
        *(root / "data").glob("*.toml"),
        root / "roles.py",
        root / "locations.py",
        root / "taxonomy.py",
    ]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


def test_rule_changes_require_a_version_bump():
    assert (TAXONOMY_VERSION, _fingerprint()) == (FINGERPRINTED_VERSION, FINGERPRINT), (
        "harmonization rules changed: bump TAXONOMY_VERSION and update FINGERPRINTED_VERSION "
        f"and FINGERPRINT (now {_fingerprint()}) in this test"
    )
