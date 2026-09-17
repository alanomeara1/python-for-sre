"""On-call rota checks: coverage gaps and double-bookings.

Spec: drills/10_intervals/variant.md
"""

from datetime import datetime
from typing import Iterable

Shift = tuple[str, datetime, datetime]


def coverage_gaps(shifts: Iterable[Shift], period_start: datetime, period_end: datetime) -> list[tuple]:
    raise NotImplementedError


def double_booked(shifts: Iterable[Shift]) -> list[tuple]:
    raise NotImplementedError
