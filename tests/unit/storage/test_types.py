from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select, text
from sqlalchemy.exc import StatementError

from jobsignal.storage.db import make_engine
from jobsignal.storage.types import UTCDateTime

EDT = timezone(timedelta(hours=-4))


@pytest.fixture
def table_and_engine(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'types.db').as_posix()}")
    metadata = MetaData()  # test-only table, deliberately not on Base
    table = Table(
        "_t", metadata, Column("id", Integer, primary_key=True), Column("at", UTCDateTime)
    )
    metadata.create_all(engine)
    return table, engine


def write_and_read(table, engine, value):
    with engine.begin() as conn:
        conn.execute(insert(table).values(id=1, at=value))
    with engine.connect() as conn:
        return conn.execute(select(table.c.at)).scalar_one()


def test_offset_datetime_round_trips_as_utc(table_and_engine):
    table, engine = table_and_engine
    stored = write_and_read(table, engine, datetime(2024, 4, 23, 16, 6, 5, tzinfo=EDT))

    assert stored == datetime(2024, 4, 23, 20, 6, 5, tzinfo=UTC)
    assert stored.utcoffset() == timedelta(0)


def test_value_is_stored_as_utc_wall_clock(table_and_engine):
    table, engine = table_and_engine
    write_and_read(table, engine, datetime(2024, 4, 23, 16, 6, 5, tzinfo=EDT))
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT at FROM _t")).scalar_one()
    assert raw.startswith("2024-04-23 20:06:05")


def test_naive_datetime_rejected_on_write(table_and_engine):
    table, engine = table_and_engine
    with pytest.raises(StatementError) as excinfo:
        write_and_read(table, engine, datetime(2024, 4, 23, 16, 6, 5))
    assert isinstance(excinfo.value.orig, ValueError)


def test_none_round_trips(table_and_engine):
    table, engine = table_and_engine
    assert write_and_read(table, engine, None) is None
