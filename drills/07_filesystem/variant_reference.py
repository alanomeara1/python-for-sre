"""Grandfather-father-son retention for db-YYYY-MM-DD.sql.gz backups.

Retention is a union of KEEP rules; deleting is everything else. Deciding
file-by-file means re-deriving every rule per file and getting the overlaps
wrong. Full reasoning in EXPLAINED.md.
"""

import re
from datetime import date
from typing import Iterable

# Anchored at both ends: "db-2026-09-01.sql.gz.tmp" (a partial upload) must not match.
BACKUP_RE = re.compile(r"^db-(\d{4}-\d{2}-\d{2})\.sql\.gz$")
SUNDAY = 6                                # date.weekday(): Monday is 0


def backups_to_delete(filenames: Iterable[str], today: date,
                      daily: int = 7, weekly: int = 4, monthly: int = 6) -> list[str]:
    # Keyed by date: gives sortable keys and de-duplicates two files claiming one day.
    backups: dict[date, str] = {}
    for name in filenames:
        match = BACKUP_RE.match(name)
        if not match:
            continue                      # not ours: never delete what we don't understand
        try:
            # Two-stage validation: the regex proves the SHAPE, fromisoformat proves the
            # date is REAL. No pattern can tell you 2026-02-30 isn't a day.
            day = date.fromisoformat(match[1])
        except ValueError:
            continue                      # right shape, impossible date (2026-02-30)
        if day > today:
            continue                      # future-dated: clock skew, leave it alone
        backups[day] = name

    newest_first = sorted(backups, reverse=True)

    # "Last N" = the N most recent backups that EXIST, not a calendar window.
    # A calendar window ("anything from the last 7 days") keeps NOTHING when the backup
    # job has been broken for a week, which is exactly when you need the old ones.
    keep = set(newest_first[:daily])
    # |= union: a Sunday that is also one of the last 7 is kept by both rules, and the
    # set makes that overlap free rather than something to reason about.
    keep |= set([d for d in newest_first if d.weekday() == SUNDAY][:weekly])
    keep |= set([d for d in newest_first if d.day == 1][:monthly])

    # Oldest first: a stable, readable delete list. The safe failure mode for retention
    # is keeping too much, never deleting something you didn't recognise.
    return sorted(backups[d] for d in backups if d not in keep)
