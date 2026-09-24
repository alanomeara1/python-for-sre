"""Run the drill 10 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
no wall-clock times, no randomness, no temp paths in the output.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference


def t(hour, minute=0):
    """A fixed clock: every timestamp in this sample is on 2026-09-17."""
    return datetime(2026, 9, 17, hour, minute)


def hhmm(moment):
    return moment.strftime("%H:%M")


def show(windows):
    return "[" + ", ".join(f"{hhmm(s)}-{hhmm(e)}" for s, e in windows) + "]"


# The reporting window is one working day. Two of these outages deliberately fall outside it.
DAY_START, DAY_END = t(9), t(17)

OUTAGES = [
    (t(8, 30), t(9, 30)),    # started before the window opened
    (t(10), t(10, 30)),      # two alerts for
    (t(10, 30), t(11)),      # ...one continuous incident: they touch
    (t(10, 45), t(10, 50)),  # a third alert, entirely inside the second
    (t(13), t(13, 20)),
    (t(16, 30), t(18)),      # still going when the window closed
]

print("## The main problem: outage windows\n")
print("A day's alerts, as (start, end) pairs. Note the pair that touch at 10:30, the one\n"
      "nested inside another, and the two that overrun the 09:00-17:00 reporting window:\n")
print("```text")
for start, end in OUTAGES:
    print(f"{hhmm(start)} - {hhmm(end)}")
print("```\n")

print("`merge_intervals(outages)` collapses them into real incidents:\n")
print("```python")
merged = reference.merge_intervals(OUTAGES)
print(f"{len(OUTAGES)} alerts -> {len(merged)} incidents")
print(show(merged))
print("```\n")

print("`total_downtime(...)` and `availability(...)`, clipped to 09:00-17:00:\n")
print("```python")
downtime = reference.total_downtime(OUTAGES, DAY_START, DAY_END)
uptime = reference.availability(OUTAGES, DAY_START, DAY_END)
print(f"total_downtime(outages, 09:00, 17:00) -> {downtime}  ({downtime.total_seconds() / 60:.0f} minutes)")
print(f"availability(outages, 09:00, 17:00)   -> {uptime:.6f}  ({uptime * 100:.2f}%)")
print("```\n")

window_minutes = (DAY_END - DAY_START).total_seconds() / 60
print(f"Reading that: 6 alerts were really {len(merged)} incidents, and merging matters — counted raw, the\n"
      "touching and nested pairs would bill the same minutes twice and understate availability.\n"
      "Only the in-window parts count: the 08:30 outage contributes 30 minutes, not 60, and the\n"
      f"16:30 one contributes 30 minutes, not 90. That is {downtime.total_seconds() / 60:.0f} minutes of the "
      f"{window_minutes:.0f}-minute day.\n")

# Three services, each with its own alert history. Service B flaps: two overlapping alerts.
BY_SERVICE = {
    "api": [(t(10), t(11)), (t(14), t(15))],
    "db": [(t(10, 30), t(11, 30)), (t(10, 45), t(12))],   # overlapping alerts from one service
    "cache": [(t(10, 45), t(11, 15)), (t(14, 30), t(14, 45))],
}

print("`concurrent_outages(...)`: when were two or more services down at once?\n")
print("```python")
for service, windows in BY_SERVICE.items():
    print(f"{service:>6}: {show(windows)}")
print()
for threshold in (2, 3):
    periods = reference.concurrent_outages(BY_SERVICE, min_services=threshold)
    print(f"concurrent_outages(by_service, min_services={threshold}) -> {show(periods)}")
print("```\n")

pairs = reference.concurrent_outages(BY_SERVICE, min_services=2)
triples = reference.concurrent_outages(BY_SERVICE, min_services=3)
print("Reading that: db raised two overlapping alerts, and each service's own windows are merged\n"
      "first, so one flapping service can never look like two. db alone is down until 12:00, but\n"
      f"the morning window where TWO are down together is only {hhmm(pairs[0][0])}-{hhmm(pairs[0][1])}; "
      f"at three it narrows\n"
      f"to {hhmm(triples[0][0])}-{hhmm(triples[0][1])}, which is the blast radius worth putting in the "
      f"incident review.\napi and cache overlap again at {hhmm(pairs[1][0])}-{hhmm(pairs[1][1])}.\n")

print("## The variant: on-call rota\n")

SHIFTS = [
    ("nadia", t(9), t(13)),
    ("ivan", t(12), t(17)),     # overlaps nadia by an hour: a handover, or a mistake
    ("ivan", t(17), t(20)),     # back-to-back with his own previous shift
    ("priya", t(18), t(22)),    # overlaps ivan's second shift
]
PERIOD_START, PERIOD_END = t(8), t(23)

print("The rota for 08:00-23:00:\n")
print("```text")
for person, start, end in SHIFTS:
    print(f"{person:<6} {hhmm(start)} - {hhmm(end)}")
print("```\n")

print("`coverage_gaps(...)` and `double_booked(...)`:\n")
print("```python")
gaps = variant_reference.coverage_gaps(SHIFTS, PERIOD_START, PERIOD_END)
print(f"coverage_gaps(shifts, 08:00, 23:00) -> {show(gaps)}")
print("double_booked(shifts) ->")
for start, end, people in variant_reference.double_booked(SHIFTS):
    print(f"    {hhmm(start)}-{hhmm(end)}  {people}")
print("```\n")

print("Reading that: nobody is on call for the first hour of the period or the last one, which is\n"
      "what you fix before the pager proves it at 22:30. The 12:00-13:00 and 18:00-20:00 overlaps\n"
      "are two people on at once: usually deliberate at a handover, but worth confirming nobody\n"
      "assumes the other is holding it. Ivan's two back-to-back shifts are treated as one person,\n"
      "so 17:00 is a clean handover rather than a phantom gap or a phantom overlap.")
