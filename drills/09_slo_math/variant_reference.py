"""Incident metrics (count, open, MTTA, MTTR) from an incident-tool CSV export."""

import csv
import io
from collections import defaultdict
from datetime import datetime
from statistics import fmean


def _parse_time(value: str) -> datetime | None:
    value = value.strip()
    return datetime.fromisoformat(value) if value else None   # 3.11+ accepts a trailing Z


def _minutes(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 60


def load_incidents(csv_text: str) -> list[dict]:
    # Parse once into typed records; every metric works on datetimes, not strings.
    return [
        {
            "id": row["id"],
            "severity": row["severity"],
            "started": _parse_time(row["started"]),
            "acknowledged": _parse_time(row["acknowledged"]),
            "resolved": _parse_time(row["resolved"]),
        }
        for row in csv.DictReader(io.StringIO(csv_text))
    ]


def incident_metrics(csv_text: str) -> dict[str, dict]:
    by_severity = defaultdict(list)
    for incident in load_incidents(csv_text):
        by_severity[incident["severity"]].append(incident)

    metrics = {}
    for severity, incidents in by_severity.items():
        # Average only what has the timestamp: counting open incidents as 0 minutes flatters MTTR.
        ack_times = [_minutes(i["started"], i["acknowledged"]) for i in incidents if i["acknowledged"]]
        fix_times = [_minutes(i["started"], i["resolved"]) for i in incidents if i["resolved"]]
        metrics[severity] = {
            "count": len(incidents),
            "open": sum(1 for i in incidents if i["resolved"] is None),
            "mtta_minutes": fmean(ack_times) if ack_times else None,
            "mttr_minutes": fmean(fix_times) if fix_times else None,
        }
    return metrics


def worst_incidents(csv_text: str, n: int, now: datetime | None = None) -> list[tuple[str, float]]:
    durations = []
    for incident in load_incidents(csv_text):
        end = incident["resolved"] or now
        if end is None:
            continue                      # open, and no "now" to measure against
        durations.append((incident["id"], _minutes(incident["started"], end)))

    durations.sort(key=lambda pair: (-pair[1], pair[0]))
    return durations[:n]
