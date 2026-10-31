"""Canonical taxonomy for harmonization, loaded from the TOML files in ``data/``.

Bump TAXONOMY_VERSION whenever any data file changes: stored results carry the version,
and the harmonize command reprocesses every posting with an older one.
"""

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from typing import Any

TAXONOMY_VERSION = "2026.11.1"


class RoleFamily(StrEnum):
    SOFTWARE_ENGINEERING = "software_engineering"
    ML_RESEARCH = "ml_research"
    DATA = "data"
    SOLUTIONS_ENGINEERING = "solutions_engineering"
    SECURITY = "security"
    PRODUCT_MANAGEMENT = "product_management"
    PROGRAM_MANAGEMENT = "program_management"
    DESIGN = "design"
    SALES = "sales"
    CUSTOMER_SUCCESS = "customer_success"
    MARKETING = "marketing"
    OPERATIONS = "operations"
    FINANCE = "finance"
    LEGAL = "legal"
    PEOPLE = "people"
    OTHER = "other"


class Seniority(StrEnum):
    INTERN = "intern"
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    STAFF_PLUS = "staff_plus"
    MANAGER = "manager"
    DIRECTOR_PLUS = "director_plus"


SENIORITY_PRECEDENCE = (
    Seniority.INTERN,
    Seniority.DIRECTOR_PLUS,
    Seniority.MANAGER,
    Seniority.STAFF_PLUS,
    Seniority.SENIOR,
    Seniority.ENTRY,
    Seniority.MID,
)

_ISO = re.compile(r"[A-Z]{2}(-[A-Z0-9]{1,3})?")


@dataclass(frozen=True)
class Taxonomy:
    family_phrases: dict[RoleFamily, tuple[str, ...]]
    department_phrases: dict[RoleFamily, tuple[str, ...]]
    seniority_phrases: dict[Seniority, tuple[str, ...]]
    ic_manager_phrases: tuple[str, ...]  # spans whose seniority words are not seniority
    countries: dict[str, str]  # alias -> ISO 3166-1 alpha-2
    regions: dict[str, str]  # alias -> ISO 3166-2
    cities: dict[str, tuple[str, str | None, str]]  # alias -> (city, region, country)
    remote_markers: tuple[str, ...]
    remote_fillers: tuple[str, ...]  # "in the", "from the" ... around remote markers
    noise_words: tuple[str, ...]  # "hq", "metro area" ... dropped before resolving
    macro_regions: dict[str, str]  # alias -> country
    unresolvable: tuple[str, ...]


def _phrases(values: Any, where: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
        raise ValueError(f"{where}: expected a list of non-empty strings")
    return tuple(v.strip().lower() for v in values)


def _iso(code: str, where: str) -> str:
    if not _ISO.fullmatch(code):
        raise ValueError(f"{where}: {code!r} is not an ISO 3166 code")
    return code


def _enum_key[E: StrEnum](enum: type[E], key: str, where: str) -> E:
    try:
        return enum(key)
    except ValueError:
        raise ValueError(f"{where}: unknown {enum.__name__} {key!r}") from None


def _build_taxonomy(raw: dict[str, dict[str, Any]]) -> Taxonomy:
    roles, seniority, places = raw["roles"], raw["seniority"], raw["places"]

    family_phrases: dict[RoleFamily, tuple[str, ...]] = {}
    department_phrases: dict[RoleFamily, tuple[str, ...]] = {}
    for key, table in roles["families"].items():
        family = _enum_key(RoleFamily, key, "roles.families")
        family_phrases[family] = _phrases(table.get("title", []), f"roles.{key}.title")
        department_phrases[family] = _phrases(table.get("department", []), f"roles.{key}.dept")

    seniority_phrases = {
        _enum_key(Seniority, key, "seniority.levels"): _phrases(v, f"seniority.{key}")
        for key, v in seniority["levels"].items()
    }

    seen: dict[str, str] = {}  # alias -> table, for cross-table uniqueness

    def claim(alias: str, table: str) -> str:
        alias = alias.strip().lower()
        if alias in seen:
            raise ValueError(f"alias {alias!r} appears in {seen[alias]} and {table}")
        seen[alias] = table
        return alias

    countries = {
        claim(alias, "countries"): _iso(code, "places.countries")
        for code, aliases in places["countries"].items()
        for alias in _phrases(aliases, f"places.countries.{code}")
    }
    regions = {
        claim(alias, "regions"): _iso(code, "places.regions")
        for code, aliases in places["regions"].items()
        for alias in _phrases(aliases, f"places.regions.{code}")
    }
    cities: dict[str, tuple[str, str | None, str]] = {}
    for name, entry in places["cities"].items():
        region = entry.get("region")
        country = _iso(entry["country"], f"places.cities.{name}")
        if region is not None:
            _iso(region, f"places.cities.{name}")
        for alias in _phrases([name, *entry.get("aliases", [])], f"places.cities.{name}"):
            cities[claim(alias, "cities")] = (name, region, country)
    macro_regions = {
        claim(alias, "macro_regions"): _iso(code, "places.macro_regions")
        for code, aliases in places["macro_regions"].items()
        for alias in _phrases(aliases, f"places.macro_regions.{code}")
    }

    return Taxonomy(
        family_phrases={f: p for f, p in family_phrases.items() if p},
        department_phrases={f: p for f, p in department_phrases.items() if p},
        seniority_phrases=seniority_phrases,
        ic_manager_phrases=_phrases(seniority["ic_manager"]["phrases"], "seniority.ic_manager"),
        countries=countries,
        regions=regions,
        cities=cities,
        remote_markers=_phrases(places["remote"]["markers"], "places.remote.markers"),
        remote_fillers=_phrases(places["remote"]["fillers"], "places.remote.fillers"),
        noise_words=_phrases(places["noise"]["words"], "places.noise.words"),
        macro_regions=macro_regions,
        unresolvable=_phrases(places["unresolvable"]["pieces"], "places.unresolvable"),
    )


def _load_raw() -> dict[str, dict[str, Any]]:
    data = files("jobsignal.harmonization.data")
    return {
        name: tomllib.loads(data.joinpath(f"{name}.toml").read_text(encoding="utf-8"))
        for name in ("roles", "seniority", "places")
    }


@cache
def load_taxonomy() -> Taxonomy:
    return _build_taxonomy(_load_raw())
