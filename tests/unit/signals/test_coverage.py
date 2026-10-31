"""Which weeks did scraping cover well enough to measure new openings?"""

from datetime import UTC, date, datetime, timedelta

from jobsignal.signals.coverage import SnapshotStat, available_weeks

MON = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)  # Monday 09:00, week of 2026-08-03


def week(n):
    return date(2026, 8, 3) + timedelta(weeks=n)


def daily(days, count=100, new=3, skip=()):
    return [SnapshotStat(MON + timedelta(days=d), count, new) for d in range(days) if d not in skip]


def test_daily_scraping_covers_full_weeks_only():
    stats = daily(29)  # Mon of week 0 .. Mon of week 4
    # week 0 starts before the first snapshot (09:00 Monday); week 4 is not over yet
    assert available_weeks(stats) == {week(1), week(2), week(3)}


def test_tuesday_to_sunday_gap_hides_that_week_and_its_backlog_week():
    """Laptop off Tue..Sun of week 2: Monday's scrape alone must not make the week measurable,
    and the next week's Monday catches the backlog."""
    stats = daily(36, skip=range(15, 21))  # days 15..20 = Tue..Sun of week 2
    weeks = available_weeks(stats)
    assert week(2) not in weeks
    assert week(3) not in weeks  # the 6-day gap reaches into Monday of week 3
    assert {week(1), week(4)} <= weeks


def test_weekly_cadence_is_judged_against_its_own_median_gap():
    stats = [SnapshotStat(MON + timedelta(weeks=k, days=1), 100, 5) for k in range(6)]
    assert available_weeks(stats) == {week(1), week(2), week(3), week(4)}


def test_missed_weekly_scrape_hides_the_weeks_it_touches():
    stats = [SnapshotStat(MON + timedelta(weeks=k, days=1), 100, 5) for k in (0, 1, 2, 4, 5, 6)]
    weeks = available_weeks(stats)
    assert week(3) not in weeks
    assert week(2) not in weeks  # the 14-day gap starts inside week 2
    assert week(5) in weeks


def test_bulk_repost_week_is_not_measurable():
    """An ok snapshot whose new ids are >= half the board is a re-import, not hiring."""
    stats = daily(29)
    stats[16] = SnapshotStat(stats[16].fetched_at, 100, 90)  # Wednesday of week 2
    assert week(2) not in available_weeks(stats)
    assert week(3) in available_weeks(stats)


def test_collapsed_board_week_is_not_measurable():
    """An ok fetch returning an (almost) empty board is a glitch, not a freeze."""
    stats = daily(29)
    stats[17] = SnapshotStat(stats[17].fetched_at, 0, 0)
    assert week(2) not in available_weeks(stats)


def test_no_snapshots_no_weeks():
    assert available_weeks([]) == set()
    assert available_weeks(daily(1)) == set()


def test_genuine_hiring_spurt_is_not_a_reimport():
    """90 new ids on a 100-posting board WITHOUT closures (board grows to 190) is real hiring."""
    stats = daily(29)
    stats[16] = SnapshotStat(stats[16].fetched_at, 190, 90)
    for i in range(17, 29):
        stats[i] = SnapshotStat(stats[i].fetched_at, 190, 3)
    assert week(2) in available_weeks(stats)
