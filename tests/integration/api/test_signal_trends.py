import pytest
from sqlalchemy import event

from jobsignal.weeks import week_start
from tests.integration.conftest import T1

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


def _mix_scenario(migrated_url):
    """A real mix_shift score (detect.score_all), then a LATER scrape adds a backdated posting."""
    from datetime import UTC, datetime, timedelta

    from jobsignal.detect import score_all
    from jobsignal.harmonization.locations import parse_locations
    from jobsignal.harmonization.roles import classify_title
    from jobsignal.models import Posting
    from jobsignal.signals.params import DetectorParams
    from jobsignal.storage.db import make_engine, make_session_factory
    from jobsignal.storage.repository import (
        finish_run,
        get_or_create_company,
        record_snapshot,
        save_harmonization,
        save_signal_run,
        start_run,
    )
    from jobsignal.storage.schema import PostingRecord

    scraped = datetime(2026, 10, 26, 9, tzinfo=UTC)  # a Monday
    computed_at = scraped + timedelta(hours=1)

    def posting(eid, title, published, fetched):
        return Posting(
            source="greenhouse", company="mixco", external_id=eid, title=title,
            location_raw="London, UK", department=None, url=f"https://x.io/mixco/{eid}",
            first_published=published, updated_at=None, fetched_at=fetched,
        )  # fmt: skip

    batch = []
    for k in range(16):  # 16 weeks of published history before the scrape
        published = scraped - timedelta(weeks=k, days=1)
        sales = 4 if k < 4 else 1  # a recent shift towards sales
        batch += [
            posting(f"s{k}-{i}", "Account Executive", published, scraped) for i in range(sales)
        ]
        batch += [posting(f"e{k}-{i}", "Software Engineer", published, scraped) for i in range(4)]

    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:

        def scrape(postings, at):
            company = get_or_create_company(session, "greenhouse", "mixco", at)
            run = start_run(session, at)
            record_snapshot(session, run, company, postings, at)
            finish_run(session, run, at)
            for row in session.query(PostingRecord).filter(PostingRecord.role_family.is_(None)):
                save_harmonization(
                    session, row, classify_title(row.title, None),
                    parse_locations(row.location_raw), "t", at,
                )  # fmt: skip
            session.commit()

        scrape(batch, scraped)
        scores = score_all(session, computed_at, DetectorParams())
        save_signal_run(session, computed_at, computed_at, DetectorParams(), scores)
        session.commit()
        later = scraped + timedelta(days=1)  # after the run: must not move its trend
        extra = posting("late-1", "Account Executive", scraped - timedelta(days=2), later)
        scrape([*[p.model_copy(update={"fetched_at": later}) for p in batch], extra], later)
    engine.dispose()


def test_trend_last_point_matches_stored_score_after_later_scrapes(migrated_url):
    from fastapi.testclient import TestClient

    from jobsignal.api.app import create_app

    _mix_scenario(migrated_url)
    with TestClient(create_app(migrated_url)) as client:
        items = client.get(
            "/api/v1/signals", params={"signals_only": "false", "detector": "mix_shift"}
        ).json()["items"]
        stored = next(i for i in items if i["role_family"] == "sales" and i["z"] is not None)
        last = trends(client, [stored["id"]]).json()[0]["points"][-1]
    assert last["z"] == pytest.approx(stored["z"])
    assert last["value"] == pytest.approx(stored["share_recent"])
