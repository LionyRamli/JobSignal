import pytest

from jobsignal.harmonization.roles import RoleClassification, classify_title
from jobsignal.harmonization.taxonomy import RoleFamily as F
from jobsignal.harmonization.taxonomy import Seniority as S  # noqa: N817 - terse test tables


def fam_sen(title, department=None):
    result = classify_title(title, department)
    return result.family, result.seniority


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Product Manager, Claude Marketplace", (F.PRODUCT_MANAGEMENT, S.MID)),
        ("Technical Program Manager, Compute", (F.PROGRAM_MANAGEMENT, S.MID)),
        ("Partner Manager", (F.SALES, S.MID)),
        ("Sr. Engineering Manager", (F.SOFTWARE_ENGINEERING, S.MANAGER)),
        ("Manager, Solutions Architecture", (F.SOLUTIONS_ENGINEERING, S.MANAGER)),
        ("Staff Product Manager, Billing", (F.PRODUCT_MANAGEMENT, S.STAFF_PLUS)),
    ],
)
def test_ic_manager_titles_are_not_people_managers(title, expected):
    assert fam_sen(title) == expected


def test_account_executive_is_not_an_executive():
    assert fam_sen("Enterprise Account Executive, Automotive") == (F.SALES, S.MID)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Staff+ Software Engineer", (F.SOFTWARE_ENGINEERING, S.STAFF_PLUS)),
        ("Sr. Staff Software Engineer - Money Team", (F.SOFTWARE_ENGINEERING, S.STAFF_PLUS)),
        ("Sr. Director, Finance", (F.FINANCE, S.DIRECTOR_PLUS)),
        ("Data Science Intern (2027 Start)", (F.DATA, S.INTERN)),
        ("Software Engineer, New Grad", (F.SOFTWARE_ENGINEERING, S.ENTRY)),
        ("Head of People", (F.PEOPLE, S.DIRECTOR_PLUS)),
        ("Sr. Manager, Sales Development", (F.SALES, S.MANAGER)),
    ],
)
def test_seniority_precedence(title, expected):
    assert fam_sen(title) == expected


def test_department_is_family_fallback_only():
    assert fam_sen("Deal Pricing Strategist, APAC", "Enterprise Sales")[0] == F.SALES
    assert fam_sen("Lakebase Navigator", "Enterprise Sales") == (F.SALES, S.MID)
    # department words never set seniority
    assert fam_sen("Software Engineer Intern", "Executive Engineering - Pipeline")[1] == S.INTERN
    assert fam_sen("Lakebase Navigator", "HQ Management")[1] == S.MID


def test_title_beats_department():
    assert fam_sen("Recruiter, G&A (Policy)", "People")[0] == F.PEOPLE
    assert fam_sen("Staff Software Engineer, Finance Engineering", "Finance")[0] == (
        F.SOFTWARE_ENGINEERING
    )


def test_evidence_lists_matched_phrases():
    result = classify_title("Sr. Forward Deployed Engineer (FDE)")
    assert result.family == F.SOLUTIONS_ENGINEERING
    assert "forward deployed engineer" in result.evidence
    assert "sr" in result.evidence


@pytest.mark.parametrize("junk", ["???", "🚀🚀", "ソフトウェアエンジニア", "x" * 512, "   "])
def test_junk_titles_fall_back_safely(junk):
    assert classify_title(junk, None) == RoleClassification(F.OTHER, S.MID, ())


def test_classifier_is_deterministic():
    title = "Staff Software Engineer, Agent Quality"
    assert classify_title(title, "Engineering") == classify_title(title, "Engineering")


def test_longest_phrase_wins_over_earliest():
    # "recruiting" (people) comes first; "data engineer" is longer and wins
    assert fam_sen("Recruiting Analytics Data Engineer")[0] == F.DATA


@pytest.mark.parametrize(
    ("title", "seniority"),
    [
        ("Staff Software Engineer - Access Management", S.STAFF_PLUS),
        ("Software Engineer, Vulnerability Management", S.MID),
        ("Product Manager, Identity & Access Management", S.MID),
    ],
)
def test_management_as_a_domain_is_not_seniority(title, seniority):
    assert fam_sen(title)[1] == seniority
