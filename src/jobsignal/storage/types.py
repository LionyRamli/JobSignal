"""Column types that behave identically on SQLite and PostgreSQL."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes in, stored as UTC, aware UTC datetimes out.

    SQLite has no timezone support: SQLAlchemy's DateTime(timezone=True) silently drops
    the offset there, so a -04:00 timestamp would read back as a naive local time.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime: timestamps must carry a timezone")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite: stored as UTC wall-clock
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
