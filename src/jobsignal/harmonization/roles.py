"""Rule-based job-title classification with spaCy's PhraseMatcher.

Family: the longest matching title phrase wins (ties: earliest in the title); the department
is consulted only when the title matches nothing. Seniority: the highest-precedence seniority
phrase wins, ignoring matches inside "IC manager" spans ("Product Manager", "Account
Executive"); no signal means ``mid``. Everything comes from the TOML data via load_taxonomy().
"""

from dataclasses import dataclass
from functools import cache

import spacy
from spacy.language import Language
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc

from jobsignal.harmonization.taxonomy import (
    SENIORITY_PRECEDENCE,
    RoleFamily,
    Seniority,
    load_taxonomy,
)


@dataclass(frozen=True)
class RoleClassification:
    family: RoleFamily
    seniority: Seniority
    evidence: tuple[str, ...]  # matched phrases in title order ("department:<phrase>" last)


@dataclass(frozen=True)
class _Matchers:
    nlp: Language
    family: PhraseMatcher
    department: PhraseMatcher
    seniority: PhraseMatcher
    ic_spans: PhraseMatcher


def _matcher(nlp: Language, tables: dict[str, tuple[str, ...]]) -> PhraseMatcher:
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    for label, phrases in tables.items():
        if phrases:
            matcher.add(label, [nlp.make_doc(p) for p in phrases])
    return matcher


@cache
def _matchers() -> _Matchers:
    taxonomy = load_taxonomy()
    nlp = spacy.blank("en")
    return _Matchers(
        nlp=nlp,
        family=_matcher(nlp, {f.value: p for f, p in taxonomy.family_phrases.items()}),
        department=_matcher(nlp, {f.value: p for f, p in taxonomy.department_phrases.items()}),
        seniority=_matcher(nlp, {s.value: p for s, p in taxonomy.seniority_phrases.items()}),
        ic_spans=_matcher(nlp, {"ic": taxonomy.ic_manager_phrases}),
    )


def _matches(matcher: PhraseMatcher, doc: Doc) -> list[tuple[str, int, int]]:
    strings = doc.vocab.strings
    return [(strings[match_id], start, end) for match_id, start, end in matcher(doc)]


def classify_title(title: str, department: str | None = None) -> RoleClassification:
    m = _matchers()
    doc = m.nlp.make_doc(title)

    family_hits = _matches(m.family, doc)
    evidence: list[tuple[int, str]] = []
    family = RoleFamily.OTHER
    if family_hits:
        label, start, end = min(family_hits, key=lambda h: (-(h[2] - h[1]), h[1]))
        family = RoleFamily(label)
        evidence.append((start, doc[start:end].text.lower()))

    ic_spans = [(start, end) for _, start, end in _matches(m.ic_spans, doc)]
    found: dict[Seniority, tuple[int, str]] = {}
    for label, start, end in _matches(m.seniority, doc):
        if any(s <= start and end <= e for s, e in ic_spans):
            continue  # "manager" in "Product Manager" is not seniority
        found.setdefault(Seniority(label), (start, doc[start:end].text.lower()))
    seniority = next((level for level in SENIORITY_PRECEDENCE if level in found), Seniority.MID)
    if seniority in found:
        evidence.append(found[seniority])

    phrases = [text for _, text in sorted(evidence)]
    if family is RoleFamily.OTHER and department:
        dept_doc = m.nlp.make_doc(department)
        dept_hits = _matches(m.department, dept_doc)
        if dept_hits:
            label, start, end = min(dept_hits, key=lambda h: (-(h[2] - h[1]), h[1]))
            family = RoleFamily(label)
            phrases.append(f"department:{dept_doc[start:end].text.lower()}")

    return RoleClassification(family, seniority, tuple(dict.fromkeys(phrases)))
