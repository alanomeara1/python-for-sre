from datetime import datetime, timezone

from pytest import approx

CSV = """\
id,severity,started,acknowledged,resolved
INC-101,SEV1,2026-09-01T10:00:00+00:00,2026-09-01T10:04:00+00:00,2026-09-01T11:30:00+00:00
INC-102,SEV2,2026-09-02T08:00:00+00:00,2026-09-02T08:20:00+00:00,2026-09-02T09:00:00+00:00
INC-103,SEV1,2026-09-03T22:15:00+00:00,2026-09-03T22:21:00+00:00,2026-09-04T00:45:00+00:00
INC-104,SEV2,2026-09-05T12:00:00Z,2026-09-05T12:10:00Z,
INC-105,SEV3,2026-09-06T09:00:00+00:00,,
INC-106,SEV2,2026-09-07T14:00:00+00:00,2026-09-07T14:30:00+00:00,2026-09-07T14:45:00+00:00
"""


def test_incident_metrics(variant):
    m = variant.incident_metrics(CSV)
    assert set(m) == {"SEV1", "SEV2", "SEV3"}
    assert m["SEV1"] == {"count": 2, "open": 0, "mtta_minutes": approx(5.0), "mttr_minutes": approx(120.0)}
    assert m["SEV2"] == {"count": 3, "open": 1, "mtta_minutes": approx(20.0), "mttr_minutes": approx(52.5)}


def test_metrics_none_when_nothing_to_average(variant):
    m = variant.incident_metrics(CSV)
    assert m["SEV3"] == {"count": 1, "open": 1, "mtta_minutes": None, "mttr_minutes": None}


def test_metrics_empty_export(variant):
    assert variant.incident_metrics("id,severity,started,acknowledged,resolved\n") == {}


def test_worst_incidents_resolved_only(variant):
    assert variant.worst_incidents(CSV, 2) == [("INC-103", approx(150.0)), ("INC-101", approx(90.0))]
    assert len(variant.worst_incidents(CSV, 10)) == 4


def test_worst_incidents_open_measured_to_now(variant):
    now = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)
    assert variant.worst_incidents(CSV, 3, now=now) == [
        ("INC-104", approx(3060.0)),
        ("INC-105", approx(1800.0)),
        ("INC-103", approx(150.0)),
    ]


def test_worst_incidents_tiebreak_by_id(variant):
    csv_text = """\
id,severity,started,acknowledged,resolved
INC-2,SEV2,2026-09-01T10:00:00+00:00,,2026-09-01T10:30:00+00:00
INC-1,SEV2,2026-09-02T10:00:00+00:00,,2026-09-02T10:30:00+00:00
"""
    assert [i for i, _ in variant.worst_incidents(csv_text, 2)] == ["INC-1", "INC-2"]
