"""Grandfather-father-son retention for db-YYYY-MM-DD.sql.gz backups.

Spec: drills/07_filesystem/variant.md
"""

from datetime import date
from typing import Iterable


def backups_to_delete(filenames: Iterable[str], today: date,
                      daily: int = 7, weekly: int = 4, monthly: int = 6) -> list[str]:
    raise NotImplementedError
