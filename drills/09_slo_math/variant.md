# 09 · Variant: incident metrics from a CSV export

Same skill as the main drill (turn raw operational data into the numbers leadership asks for),
this time with `csv` and `datetime`. It's very likely for a manager role: "what's our MTTR by severity?"

## The task

> Here's an export from our incident tool. Give me, per severity: how many incidents, how many
> are still open, mean time to acknowledge and mean time to resolve, in minutes. Also give me the
> N longest incidents.

```csv
id,severity,started,acknowledged,resolved
INC-101,SEV1,2026-09-01T10:00:00+00:00,2026-09-01T10:04:00+00:00,2026-09-01T11:30:00+00:00
INC-104,SEV2,2026-09-05T12:00:00Z,2026-09-05T12:10:00Z,
INC-105,SEV3,2026-09-06T09:00:00+00:00,,
```

Empty `resolved` = still open. Empty `acknowledged` = nobody has acked it yet.

## Contract

```python
def incident_metrics(csv_text: str) -> dict[str, dict]
    # -> {"SEV1": {"count": 2, "open": 0, "mtta_minutes": 5.0, "mttr_minutes": 120.0}, ...}
    # MTTA = mean(acknowledged - started) over incidents that HAVE an ack
    # MTTR = mean(resolved - started) over incidents that ARE resolved
    # None when there is nothing to average

def worst_incidents(csv_text: str, n: int, now: datetime | None = None) -> list[tuple[str, float]]
    # [(id, duration_minutes), ...] longest first; ties broken by id ascending.
    # Open incidents: included, measured up to `now`, if now is given. Otherwise skipped.
```

## Say this out loud

- "`csv.DictReader` over `io.StringIO(text)`. Same code works with an open file."
- "I parse into typed records once, then compute. I don't re-parse strings in every metric."
- "Means only over incidents that have the timestamp. Treating open incidents as zero duration
  would make MTTR look *better* the worse things are."
- "All timestamps must be timezone-aware. Mixing naive and aware datetimes raises `TypeError` on subtraction."
- "MTTR is a mean, so one 3-day incident dominates it. I'd show the median and the worst-N alongside it,
  and I'd be careful about using MTTR as a team target, because it gets gamed by closing incidents early."
