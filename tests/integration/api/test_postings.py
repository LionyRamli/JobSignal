import pytest
from sqlalchemy import event

pytestmark = pytest.mark.integration


def external_ids(body):
    return sorted(item["external_id"] for item in body["items"])


def test_filters_combine(seeded_api):
    body = seeded_api.get(
        "/api/v1/postings", params={"company": "acme", "role_family": "sales", "country": "GB"}
    ).json()
    assert external_ids(body) == ["1", "6"]
    assert body["next_cursor"] is None


def test_open_only_by_default_and_open_false_includes_closed(seeded_api):
    assert "4" not in external_ids(
        seeded_api.get("/api/v1/postings", params={"company": "acme"}).json()
    )
    closed = seeded_api.get("/api/v1/postings", params={"company": "acme", "open": "false"}).json()
    assert external_ids(closed) == ["1", "2", "3", "4", "6"]


def test_seniority_filter(seeded_api):
    body = seeded_api.get("/api/v1/postings", params={"seniority": "senior"}).json()
    assert external_ids(body) == ["6"]


def test_pagination_walks_all_rows_once(seeded_api):
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = seeded_api.get("/api/v1/postings", params=params).json()
        seen += [item["id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert len(seen) == len(set(seen)) == 5  # acme 1,2,3,6 + beta 5 are open
    assert seen == sorted(seen)


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"limit": "x"}, {"cursor": "garbage"}, {"cursor": "LTE="}],
)
def test_bad_pagination_params_are_422(seeded_api, params):
    assert seeded_api.get("/api/v1/postings", params=params).status_code == 422


def test_posting_detail_has_locations(seeded_api):
    first = seeded_api.get(
        "/api/v1/postings", params={"company": "acme", "role_family": "sales"}
    ).json()
    posting_id = first["items"][0]["id"]
    body = seeded_api.get(f"/api/v1/postings/{posting_id}").json()
    assert body["company"] == "acme"
    assert body["role_family"] == "sales"
    assert [loc["key"] for loc in body["locations"]] == ["city|GB|GB-ENG|London"]
    assert body["first_seen_at"].endswith("Z")
    assert body["closed_at"] is None


def test_unknown_posting_is_404(seeded_api):
    response = seeded_api.get("/api/v1/postings/999999")
    assert (response.status_code, response.json()) == (404, {"detail": "posting not found"})


def test_no_n_plus_one(seeded_api):
    statements = []

    def record(conn, cursor, statement, *args):
        if "sqlite_master" not in statement and not statement.startswith("PRAGMA"):
            statements.append(statement)

    engine = seeded_api.app.state.engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert (
            seeded_api.get("/api/v1/postings", params={"limit": 50, "open": "false"}).status_code
            == 200
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) <= 4, statements


def test_country_filter_alone(seeded_api):
    assert external_ids(seeded_api.get("/api/v1/postings", params={"country": "GB"}).json()) == [
        "1",
        "6",
    ]
    us = external_ids(seeded_api.get("/api/v1/postings", params={"country": "US"}).json())
    assert us == ["2", "3", "5"]
