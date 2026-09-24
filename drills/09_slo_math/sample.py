"""Run the drill 09 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
fixed inputs, a fixed `now`, no measured durations.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

# Ten request latencies in ms: mostly fast, with the long tail that percentiles exist for.
LATENCIES = [12, 15, 18, 21, 24, 30, 45, 80, 120, 350]

print("## The main problem: the numbers behind an SLO\n")
print(f"Ten request latencies in milliseconds: {LATENCIES}\n")
print("`percentile(values, p)`, nearest-rank:\n")
print("```python")
for p in (0, 50, 90, 95, 99, 100):
    print(f"percentile(latencies, {p:>3})  -> {reference.percentile(LATENCIES, p):>6.1f} ms")
print("```\n")

print("Reading that: every answer is a latency some request actually had. Nearest-rank never\n"
      "invents a value, unlike the interpolating method numpy uses by default — worth one\n"
      "sentence out loud, because the two disagree and either is defensible if you say which.\n"
      "\n"
      "Notice p95 and p99 are both 350ms, the single slowest request. With 10 samples there is\n"
      "nothing else they could be: you cannot measure a 99th percentile from 10 data points,\n"
      "and a dashboard showing p99 over a thin time slice is mostly showing you its own noise.\n")

print("A day's traffic: 100,000 requests, 350 of them failed, against a 99.9% SLO.\n")
print("```python")
good, total, slo = 99_650, 100_000, 0.999
print(f"availability(good={good}, total={total})".ljust(52)
      + f" -> {reference.availability(good, total):.5f}")
print(f"error_budget_remaining(slo={slo}, good={good}, total={total})".ljust(52)
      + f" -> {reference.error_budget_remaining(slo, good, total):.2f}")
print(f"burn_rate(slo={slo}, error_rate=0.0035)".ljust(52)
      + f" -> {reference.burn_rate(slo, 0.0035):.2f}")
print("```\n")

print("Reading that: 99.65% available sounds fine until you compare it to the target. The SLO\n"
      "allows 0.1% to fail and 0.35% did, so the budget is not merely spent, it is overspent:\n"
      "-2.50 means you burned three and a half times the month's allowance. The negative is\n"
      "deliberate — clamping it at zero would hide exactly the number that justifies stopping\n"
      "feature work. A burn rate of 3.5 says the same thing per unit time: at this pace you\n"
      "consume a 30-day budget in about 8.5 days.\n")

print("A healthier day, same SLO:\n")
print("```python")
good = 99_950
print(f"availability(good={good}, total={total})".ljust(52)
      + f" -> {reference.availability(good, total):.5f}")
print(f"error_budget_remaining(slo={slo}, good={good}, total={total})".ljust(52)
      + f" -> {reference.error_budget_remaining(slo, good, total):.2f}")
print("```\n")

print("Reading that: 50 failures out of 100,000 is half the allowance, so 0.50 of the budget is\n"
      "left. That is the number a release decision actually hangs on.\n")

print("Whether to wake somebody, `should_page(slo, short_window, long_window)`. The rule is\n"
      "multiwindow: a long window says it is significant, a short one says it is still happening.\n")
print("```python")
scenarios = [
    ("hard outage, ongoing", 0.020, 0.020),
    ("brief blip, already over", 0.000, 0.020),
    ("slow burn, not yet urgent", 0.020, 0.001),
    ("healthy", 0.000, 0.000),
]
print(f"{'scenario':<28} {'short':>7} {'long':>7} {'burn(short)':>12} {'burn(long)':>11}  page?")
for label, short, long in scenarios:
    print(f"{label:<28} {short:>7.3f} {long:>7.3f} "
          f"{reference.burn_rate(slo, short):>12.1f} {reference.burn_rate(slo, long):>11.1f}  "
          f"{reference.should_page(slo, short, long)}")
print("```\n")

print("Reading that: only the first pages, and the other three are the reason the rule is an AND.\n"
      "The blip has a terrible long-window number but the short window is clean, so it has\n"
      "already recovered — paging on the long window alone keeps the pager going for an hour\n"
      "after the fix. The slow burn is the mirror image: the short window looks alarming but\n"
      "nothing sustained is happening, and paging on that alone means being woken by every\n"
      "transient spike. 14.4 is where the threshold comes from: 30 days is 720 hours, and\n"
      "spending 2% of the budget in a single hour is 0.02 x 720 = 14.4.\n")

# ---------------------------------------------------------------------------

INCIDENTS = """\
id,severity,started,acknowledged,resolved
INC-101,SEV1,2026-09-01T02:00:00+00:00,2026-09-01T02:04:00+00:00,2026-09-01T03:10:00+00:00
INC-102,SEV1,2026-09-03T14:00:00+00:00,2026-09-03T14:12:00+00:00,
INC-103,SEV2,2026-09-05T09:00:00+00:00,2026-09-05T09:30:00+00:00,2026-09-05T11:00:00+00:00
INC-104,SEV2,2026-09-07T22:00:00+00:00,,2026-09-08T04:00:00+00:00
INC-105,SEV3,2026-09-09T11:00:00+00:00,2026-09-09T11:05:00+00:00,2026-09-09T11:25:00+00:00
"""

NOW = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)

print("## The variant: incident metrics from a CSV export\n")
print("Input, straight out of the incident tool. INC-102 is still open, and INC-104 was never\n"
      "acknowledged — someone just fixed it:\n")
print("```csv")
print(INCIDENTS.rstrip())
print("```\n")

print("`incident_metrics(csv_text)`:\n")
print("```json")
print(json.dumps(variant_reference.incident_metrics(INCIDENTS), indent=2))
print("```\n")

print("Reading that: MTTR for SEV1 is 70 minutes, and that is INC-101 alone. INC-102 is still\n"
      "burning and is counted in `open` instead. Folding it in as zero would make the mean look\n"
      "better the longer the outage ran, which is the classic way an incident dashboard lies.\n"
      "\n"
      "SEV2 shows the same idea on the other field: MTTA covers only INC-103, because INC-104\n"
      "has no acknowledgement at all. `None` rather than 0.0 is the honest answer when there is\n"
      "nothing to average, and it renders as n/a instead of an impressive-looking zero.\n")

print("The mean hides the shape, so `worst_incidents(csv_text, n, now=...)` sits beside it:\n")
print("```python")
print(f"worst_incidents(csv, 3, now=2026-09-10T00:00Z) -> {variant_reference.worst_incidents(INCIDENTS, 3, now=NOW)}")
print(f"worst_incidents(csv, 3)                        -> {variant_reference.worst_incidents(INCIDENTS, 3)}")
print("```\n")

print("Reading that: with a `now`, the open incident is measured up to it and dominates the\n"
      "list at 9,240 minutes — six and a half days and still running. Without one it is skipped\n"
      "entirely. That is an explicit choice at the call site rather than a hidden default,\n"
      "which matters when the number ends up in a report someone acts on.")
