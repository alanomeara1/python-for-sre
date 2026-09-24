"""Incident metrics (count, open, MTTA, MTTR) from an incident-tool CSV export.

Parse once into typed records, then compute. Averages cover only what has the
timestamp, because counting open incidents as zero duration makes MTTR look
better the worse things get. Full reasoning in EXPLAINED.md.
"""

import csv
import io
from collections import defaultdict
from datetime import datetime
from statistics import fmean


def _parse_time(value: str) -> datetime | None:
    # Empty cell means "hasn't happened yet" (no ack, not resolved), which is data,
    # not an error: None flows through and the metrics filter on it.
    value = value.strip()
    return datetime.fromisoformat(value) if value else None   # 3.11+ accepts a trailing Z


def _minutes(start: datetime, end: datetime) -> float:
    # One place that knows the unit. Mixing naive and aware datetimes raises TypeError
    # on subtraction, so the export must be timezone-aware throughout.
    return (end - start).total_seconds() / 60


def load_incidents(csv_text: str) -> list[dict]:
    # DictReader keys rows by the header, so a new column can't shift everything.
    # StringIO makes text behave like an open file: identical code works on a handle,
    # and the tests need no filesystem.
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
    # Group first, then compute per group: severities appear as they're found, so an
    # export with no SEV1s simply has no SEV1 key rather than a fabricated zero row.
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
            # Counted separately rather than folded into the mean, so "still burning"
            # can't hide inside an average.
            "open": sum(1 for i in incidents if i["resolved"] is None),
            # None, not 0.0: no resolved incidents means there IS no MTTR, and 0.0 would
            # claim instant fixes. The dashboard renders n/a and the reader notices.
            "mtta_minutes": fmean(ack_times) if ack_times else None,
            "mttr_minutes": fmean(fix_times) if fix_times else None,
        }
    return metrics


def worst_incidents(csv_text: str, n: int, now: datetime | None = None) -> list[tuple[str, float]]:
    durations = []
    for incident in load_incidents(csv_text):
        # Passing `now` means "measure open incidents up to here"; omitting it skips
        # them. An explicit choice at the call site, not a hidden default.
        end = incident["resolved"] or now
        if end is None:
            continue                      # open, and no "now" to measure against
        durations.append((incident["id"], _minutes(incident["started"], end)))

    # Two-key sort: longest first, ties broken by id so the output is deterministic.
    durations.sort(key=lambda pair: (-pair[1], pair[0]))
    # MTTR is a mean, so one three-day incident dominates the quarter: this list is what
    # you show alongside it, with the median.
    return durations[:n]
