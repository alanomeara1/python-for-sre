"""Outage windows: merge, downtime, availability, concurrent failures.

Spec: drills/10_intervals/README.md
"""

from typing import Iterable


def merge_intervals(intervals: Iterable[tuple]) -> list[tuple]:
    raise NotImplementedError


def total_downtime(outages, window_start, window_end):
    raise NotImplementedError


def availability(outages, window_start, window_end) -> float:
    raise NotImplementedError


def concurrent_outages(outages_by_service: dict[str, list[tuple]], min_services: int) -> list[tuple]:
    raise NotImplementedError
