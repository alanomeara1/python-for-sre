"""Grandfather-father-son retention for db-YYYY-MM-DD.sql.gz backups."""

import re
from datetime import date
from typing import Iterable

BACKUP_RE = re.compile(r"^db-(\d{4}-\d{2}-\d{2})\.sql\.gz$")
SUNDAY = 6                                # date.weekday(): Monday is 0


def backups_to_delete(filenames: Iterable[str], today: date,
                      daily: int = 7, weekly: int = 4, monthly: int = 6) -> list[str]:
    backups: dict[date, str] = {}
    for name in filenames:
        match = BACKUP_RE.match(name)
        if not match:
            continue                      # not ours: never delete what we don't understand
        try:
            day = date.fromisoformat(match[1])
        except ValueError:
            continue                      # right shape, impossible date (2026-02-30)
        if day > today:
            continue                      # future-dated: clock skew, leave it alone
        backups[day] = name

    newest_first = sorted(backups, reverse=True)

    # "Last N" = the N most recent backups that EXIST, not a calendar window.
    keep = set(newest_first[:daily])
    keep |= set([d for d in newest_first if d.weekday() == SUNDAY][:weekly])
    keep |= set([d for d in newest_first if d.day == 1][:monthly])

    return sorted(backups[d] for d in backups if d not in keep)
