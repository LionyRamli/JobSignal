import pytest

from jobsignal.harmonization.locations import (
    CanonicalLocation,
    LocationKind,
    LocationParse,
    parse_locations,
    split_pieces,
)


def keys(raw):
    return [loc.key for loc in parse_locations(raw).locations]


def test_key_format():
    loc = CanonicalLocation(LocationKind.CITY, "US", "US-CA", "San Francisco")
    assert loc.key == "city|US|US-CA|San Francisco"
    assert CanonicalLocation(LocationKind.REMOTE, None, None, None).key == "remote|||"


def test_mixed_separators_and_remote_pieces():
    assert keys("California; New York; Remote - Colorado | US-Remote") == [
        "region|US|US-CA|",
        "region|US|US-NY|",
        "remote|US|US-CO|",
        "remote|US||",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Washington, DC", "region|US|US-DC|"),
        ("Washington D.C.", "region|US|US-DC|"),
        ("Remote - Washington D.C.", "remote|US|US-DC|"),
        ("Seattle, Washington", "city|US|US-WA|Seattle"),
        ("Remote - Washington", "remote|US|US-WA|"),
    ],
)
def test_washington_dc_vs_state(raw, expected):
    assert keys(raw) == [expected]


@pytest.mark.parametrize(
    ("variants", "expected"),
    [
        (["San Francisco, CA", "San Francisco, California", "San Francisco", "SF", "US-SF-HQ"],
         "city|US|US-CA|San Francisco"),
        (["Bengaluru, India", "Bangalore", "IN-Bengaluru", "India, Bangalore"],
         "city|IN|IN-KA|Bengaluru"),
        (["Toronto, Canada", "Toronto, CA", "CA-Toronto", "Toronto"], "city|CA|CA-ON|Toronto"),
        (["New York City, NY", "New York, NY", "NYC", "US-NYC", "NYC-Privy"],
         "city|US|US-NY|New York City"),
    ],
)  # fmt: skip
def test_city_forms_agree(variants, expected):
    for raw in variants:
        assert keys(raw) == [expected], raw


def test_country_and_macro_region():
    assert keys("United States") == ["country|US||"]
    assert keys("US") == ["country|US||"]
    assert keys("Northeast - United States") == ["country|US||"]
    assert keys("London, UK") == ["city|GB|GB-ENG|London"]
    assert keys("Ontario, CAN") == ["region|CA|CA-ON|"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Remote-Friendly (Travel-Required)", ["remote|||"]),
        ("Remote-Friendly, Australia", ["remote|AU||"]),
        ("Remote in the US", ["remote|US||"]),
        ("CA-Remote", ["remote|CA||"]),
        ("US-Remote-CA", ["remote|US|US-CA|"]),
        ("Sweden (Remote)", ["remote|SE||"]),
        ("SF, NYC, remote", ["city|US|US-CA|San Francisco", "city|US|US-NY|New York City",
                             "remote|||"]),
    ],
)  # fmt: skip
def test_remote_friendly_variants(raw, expected):
    assert keys(raw) == expected


def test_comma_lists_of_cities():
    assert keys("San Francisco, CA, New York City, NY, Seattle, WA") == [
        "city|US|US-CA|San Francisco",
        "city|US|US-NY|New York City",
        "city|US|US-WA|Seattle",
    ]
    assert keys("Dublin, London") == ["city|IE||Dublin", "city|GB|GB-ENG|London"]


def test_missing_and_na_locations():
    assert parse_locations(None) == LocationParse((), ())
    assert parse_locations("   ") == LocationParse((), ())
    assert parse_locations("N/A") == LocationParse((), ("N/A",))


def test_unknown_piece_reported_not_guessed():
    result = parse_locations("Atlantis; Seattle")
    assert [loc.key for loc in result.locations] == ["city|US|US-WA|Seattle"]
    assert result.unresolved == ("Atlantis",)


def test_duplicates_removed_order_kept():
    assert keys("Seattle | SF | Seattle, WA | SEA") == [
        "city|US|US-WA|Seattle",
        "city|US|US-CA|San Francisco",
    ]


def test_split_pieces():
    assert split_pieces("Sydney Or Melbourne") == ["Sydney", "Melbourne"]
    assert split_pieces("US / Canada") == ["US", "Canada"]
    assert split_pieces("Berlin and Munich") == ["Berlin", "Munich"]
    assert split_pieces("N/A") == ["N/A"]
    assert split_pieces(" a |  ; b ") == ["a", "b"]


def test_iso_prefix_must_agree_with_the_place():
    result = parse_locations("CA-Seattle")  # Seattle is not in Canada
    assert result.locations == ()
    assert result.unresolved == ("CA-Seattle",)
