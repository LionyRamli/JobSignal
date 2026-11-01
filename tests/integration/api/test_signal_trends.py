import pytest
from sqlalchemy import event

from jobsignal.weeks import week_start
from tests.integration.api.conftest import T1

pytestmark = pytest.mark.integration


def all_scores(client):
    return client.get("/api/v1/signals", params={"signals_only": "false"}).json()["items"]


def trends(client, ids):
    return client.get("/api/v1/signals/trends", params={"ids": ids})


def test_signal_trends_batch_shape(seeded_api):
    scores = all_scores(seeded_api)
    ids = [s["id"] for s in scores]
    body = trends(seeded_api, [*reversed(ids), 999999, ids[0]]).json()
    assert [t["signal_id"] for t in body] == list(reversed(ids))  # request order, deduped
    by_id = {s["id"]: s for s in scores}
    for item in body:
        assert len(item["points"]) == 8
        assert item["points"][-1]["week_start"] == week_start(T1).isoformat()
        expected = "share" if by_id[item["signal_id"]]["detector"] == "mix_shift" else "count"
        assert item["metric"] == expected


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?" + "&".join(f"ids={i}" for i in range(1, 52)),
        "?ids=0",
        "?ids=99999999999999999999",
        "?ids=abc",
    ],
)
def test_signal_trends_ids_bounds(seeded_api, query):
    assert seeded_api.get(f"/api/v1/signals/trends{query}").status_code == 422


def test_signal_trends_route_not_shadowed(seeded_api):
    first = all_scores(seeded_api)[0]["id"]
    assert trends(seeded_api, [first]).status_code == 200


def count_statements(client, ids):
    recorded = []

    def record(conn, cursor, statement, *args):
        if "sqlite_master" not in statement and not statement.startswith("PRAGMA"):
            recorded.append(statement)

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert trends(client, ids).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(recorded)


def test_signal_trends_statement_count_independent_of_ids(seeded_api):
    acme = [s["id"] for s in all_scores(seeded_api) if s["company"] == "acme"]
    assert len(acme) == 3
    assert count_statements(seeded_api, acme[:1]) == count_statements(seeded_api, acme)
