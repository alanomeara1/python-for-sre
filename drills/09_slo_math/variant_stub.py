"""Incident metrics (count, open, MTTA, MTTR) from an incident-tool CSV export.

Spec: drills/09_slo_math/variant.md
"""

from datetime import datetime


def incident_metrics(csv_text: str) -> dict[str, dict]:
    raise NotImplementedError


def worst_incidents(csv_text: str, n: int, now: datetime | None = None) -> list[tuple[str, float]]:
    raise NotImplementedError
