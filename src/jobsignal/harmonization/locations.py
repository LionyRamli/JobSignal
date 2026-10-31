"""Parse raw ATS location strings into canonical places (gazetteer in data/places.toml).

A raw string is split into pieces (``|``, ``;``, ``&``, `` or ``, `` and ``, ``/``). Each piece
is resolved in order: whole-piece alias, ISO-country prefix (``US-SF``, ``CA-Remote``), remote
markers (``Remote - Texas``), then a greedy walk over comma parts that pairs ``City, Region``,
``City, Country``, ``Region, Country`` and ``Country, City`` only when they agree. Anything
unresolved is reported, never guessed.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

from jobsignal.harmonization.taxonomy import Taxonomy, load_taxonomy


class LocationKind(StrEnum):
    CITY = "city"
    REGION = "region"
    COUNTRY = "country"
    REMOTE = "remote"


@dataclass(frozen=True)
class CanonicalLocation:
    kind: LocationKind
    country_code: str | None
    region_code: str | None
    city: str | None

    @property
    def key(self) -> str:
        return "|".join(
            [self.kind.value, *(v or "" for v in (self.country_code, self.region_code, self.city))]
        )


@dataclass(frozen=True)
class LocationParse:
    locations: tuple[CanonicalLocation, ...]  # deduplicated, input order
    unresolved: tuple[str, ...]  # original text of pieces/parts that could not be resolved


_PIECE_SPLIT = re.compile(r"\s*(?:\||;|&|\s+or\s+|\s+and\s+)\s*", re.IGNORECASE)
_NA = re.compile(r"\s*n\s*/\s*a\s*", re.IGNORECASE)
_ISO_PREFIX = re.compile(r"([a-z]{2})\s*-\s*(.+)")
_EDGE_JUNK = " -,()"
MAX_RAW_LENGTH = 4_000  # longest real string seen: ~400 chars


def split_pieces(raw: str) -> list[str]:
    pieces: list[str] = []
    for chunk in _PIECE_SPLIT.split(raw):
        parts = [chunk] if _NA.fullmatch(chunk) else chunk.split("/")
        pieces.extend(p.strip() for p in parts if p.strip())
    return pieces


@dataclass(frozen=True)
class _Gazetteer:
    taxonomy: Taxonomy
    iso_countries: frozenset[str]
    noise: re.Pattern[str]
    remote: re.Pattern[str]
    fillers: re.Pattern[str]


def _words(phrases: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alternatives})(?![a-z0-9])")


@cache
def _gazetteer() -> _Gazetteer:
    t = load_taxonomy()
    return _Gazetteer(
        taxonomy=t,
        iso_countries=frozenset(t.countries.values())
        | frozenset(c for _, _, c in t.cities.values()),
        noise=_words(t.noise_words),
        remote=_words(t.remote_markers),
        fillers=_words(t.remote_fillers),
    )


def _normalize(text: str) -> str:
    g = _gazetteer()
    text = g.noise.sub(" ", text.strip().lower())
    return " ".join(text.split()).strip(_EDGE_JUNK)


def _country_of(text: str) -> str | None:
    g = _gazetteer()
    if text in g.taxonomy.countries:
        return g.taxonomy.countries[text]
    return text.upper() if text.upper() in g.iso_countries else None


def _lookup(text: str) -> CanonicalLocation | None:
    t = _gazetteer().taxonomy
    if text in t.cities:
        city, region, country = t.cities[text]
        return CanonicalLocation(LocationKind.CITY, country, region, city)
    if text in t.regions:
        code = t.regions[text]
        return CanonicalLocation(LocationKind.REGION, code[:2], code, None)
    if text in t.macro_regions:
        return CanonicalLocation(LocationKind.COUNTRY, t.macro_regions[text], None, None)
    if text in t.countries:
        return CanonicalLocation(LocationKind.COUNTRY, t.countries[text], None, None)
    return None


def _as_remote(place: CanonicalLocation | None) -> CanonicalLocation:
    if place is None:
        return CanonicalLocation(LocationKind.REMOTE, None, None, None)
    return CanonicalLocation(LocationKind.REMOTE, place.country_code, place.region_code, None)


def _resolve_simple(text: str, allow_prefix: bool = True) -> CanonicalLocation | None:
    """One comma-free (or whole-alias) normalized piece."""
    if not text:
        return None
    if (direct := _lookup(text)) is not None:
        return direct

    g = _gazetteer()
    prefix = _ISO_PREFIX.fullmatch(text)
    if allow_prefix and prefix and prefix[1].upper() in g.iso_countries:
        code = prefix[1].upper()
        inner = _resolve_simple(prefix[2].strip(_EDGE_JUNK), allow_prefix=False)  # one level
        if inner is None:
            return None
        if inner.kind is LocationKind.REMOTE and inner.country_code is None:
            return CanonicalLocation(LocationKind.REMOTE, code, None, None)
        return inner if inner.country_code == code else None

    if g.remote.search(text):
        rest = g.fillers.sub(" ", g.remote.sub(" ", text))
        rest = " ".join(rest.split()).strip(_EDGE_JUNK)
        if not rest:
            return _as_remote(None)
        inner = _resolve_simple(rest, allow_prefix=allow_prefix)
        return _as_remote(inner) if inner is not None else None
    return None


def _is_bare_remote(text: str) -> bool:
    g = _gazetteer()
    return bool(text) and not g.fillers.sub("", g.remote.sub("", text)).strip(_EDGE_JUNK + " ")


def _resolve_piece(piece: str) -> tuple[list[CanonicalLocation], list[str]]:
    t = _gazetteer().taxonomy
    whole = _normalize(piece)
    if not whole:  # only noise words (e.g. 'Hybrid')
        return [], [piece]
    if (direct := _resolve_simple(whole)) is not None:
        return [direct], []

    originals = [p.strip() for p in piece.split(",")]
    parts = [_normalize(p) for p in originals]
    found: list[CanonicalLocation] = []
    unresolved: list[str] = []
    i = 0
    while i < len(parts):
        a, b = parts[i], parts[i + 1] if i + 1 < len(parts) else None
        if not a:
            i += 1
            continue
        if b:
            pair = _resolve_pair(a, b)
            if pair is not None:
                found.append(pair)
                i += 2
                continue
        if a in t.unresolvable or (single := _resolve_simple(a)) is None:
            unresolved.append(originals[i])
        else:
            found.append(single)
        i += 1
    return found, unresolved


def _resolve_pair(a: str, b: str) -> CanonicalLocation | None:
    """Two adjacent comma parts that describe ONE place, or None."""
    t = _gazetteer().taxonomy
    if a in t.cities:
        city, region, country = t.cities[a]
        if (region is not None and t.regions.get(b) == region) or _country_of(b) == country:
            return CanonicalLocation(LocationKind.CITY, country, region, city)
    if a in t.regions:
        code = t.regions[a]
        if _country_of(b) == code[:2]:
            return CanonicalLocation(LocationKind.REGION, code[:2], code, None)
    if _is_bare_remote(a):
        place = _lookup(b)
        if place is not None and place.kind in (LocationKind.COUNTRY, LocationKind.REGION):
            return _as_remote(place)
    country = _country_of(a) if a in t.countries else None
    if country is not None and b in t.cities and t.cities[b][2] == country:
        city, region, _ = t.cities[b]
        return CanonicalLocation(LocationKind.CITY, country, region, city)
    return None


def parse_locations(raw: str | None) -> LocationParse:
    if raw is None or not raw.strip():
        return LocationParse((), ())
    locations: dict[str, CanonicalLocation] = {}
    unresolved: list[str] = []
    pieces = split_pieces(raw[:MAX_RAW_LENGTH])
    if len(raw) > MAX_RAW_LENGTH:
        pieces = pieces[:-1]  # the cut-off last piece is noise, not an unresolved place
    for piece in pieces:
        found, missed = _resolve_piece(piece)
        for loc in found:
            locations.setdefault(loc.key, loc)
        unresolved.extend(missed)
    return LocationParse(tuple(locations.values()), tuple(dict.fromkeys(unresolved)))
