import random
from datetime import date, timedelta

TODAY = date(2026, 9, 17)   # a Thursday


def name(d):
    return f"db-{d.isoformat()}.sql.gz"


def daily_range(start, end):
    days = (end - start).days
    return [name(start + timedelta(days=i)) for i in range(days + 1)]


def test_standard_gfs(variant):
    files = daily_range(date(2026, 6, 25), TODAY)
    keep = {
        # last 7 daily
        "db-2026-09-11.sql.gz", "db-2026-09-12.sql.gz", "db-2026-09-13.sql.gz", "db-2026-09-14.sql.gz",
        "db-2026-09-15.sql.gz", "db-2026-09-16.sql.gz", "db-2026-09-17.sql.gz",
        # last 4 Sundays (09-13 is already a daily)
        "db-2026-09-06.sql.gz", "db-2026-08-30.sql.gz", "db-2026-08-23.sql.gz",
        # last 3 firsts of the month
        "db-2026-09-01.sql.gz", "db-2026-08-01.sql.gz", "db-2026-07-01.sql.gz",
    }
    result = variant.backups_to_delete(files, TODAY, daily=7, weekly=4, monthly=3)
    assert result == sorted(set(files) - keep)
    assert len(result) == len(files) - 13


def test_most_recent_existing_not_calendar_window(variant):
    # Backups stopped on 2026-08-10, more than a month before today.
    files = daily_range(date(2026, 8, 1), date(2026, 8, 10))
    result = variant.backups_to_delete(files, TODAY, daily=3, weekly=1, monthly=1)
    # keep: 08-08, 08-09, 08-10 (daily) + 08-09 (Sunday) + 08-01 (monthly)
    assert result == [name(date(2026, 8, d)) for d in range(2, 8)]


def test_ignores_unrecognised_invalid_and_future(variant):
    files = daily_range(date(2026, 9, 10), TODAY) + [
        "db-2026-09-20.sql.gz",          # future
        "db-2026-02-30.sql.gz",          # impossible date
        "db-2026-09-01.sql",             # wrong extension
        "db-2026-09-01.sql.gz.tmp",      # partial upload
        "notes.txt",
    ]
    result = variant.backups_to_delete(files, TODAY, daily=2, weekly=0, monthly=0)
    assert result == [name(date(2026, 9, d)) for d in range(10, 16)]


def test_output_sorted_regardless_of_input_order(variant):
    files = daily_range(date(2026, 9, 1), TODAY)
    shuffled = files[:]
    random.Random(42).shuffle(shuffled)
    assert variant.backups_to_delete(shuffled, TODAY, 7, 4, 6) == variant.backups_to_delete(files, TODAY, 7, 4, 6)
    assert variant.backups_to_delete(iter(shuffled), TODAY) == sorted(variant.backups_to_delete(files, TODAY))


def test_nothing_to_delete(variant):
    assert variant.backups_to_delete([], TODAY) == []
    assert variant.backups_to_delete(daily_range(date(2026, 9, 12), TODAY), TODAY) == []
