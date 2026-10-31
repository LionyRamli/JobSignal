"""ISO-week helpers shared by storage and signals (weeks start Monday 00:00 UTC)."""

from datetime import UTC, date, datetime, timedelta


def week_start(ts: datetime) -> date:
    """Monday (UTC) of the ISO week containing ``ts``."""
    day = ts.astimezone(UTC).date()
    return day - timedelta(days=day.weekday())
