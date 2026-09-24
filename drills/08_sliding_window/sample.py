"""Run the drill 08 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
every timestamp below is a fixed number of seconds, never a real clock.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

# (timestamp in seconds, ok) — a quiet start, then a burst of failures at t=10.
EVENTS = [
    (0.0, True), (1.0, True), (2.0, True), (3.0, True), (4.0, True),
    (10.0, False), (11.0, False), (12.0, True),
]

print("## The main problem: a sliding-window error-rate alert\n")
print("`ErrorRateMonitor(window_seconds=60, threshold=0.1, min_requests=5)` fed this timeline\n"
      "(seconds since the process started, and whether the request succeeded):\n")
print("```python")
for timestamp, ok in EVENTS:
    print(f"record(timestamp={timestamp:>5}, ok={ok})")
print("```\n")

monitor = reference.ErrorRateMonitor(window_seconds=60, threshold=0.1, min_requests=5)
for timestamp, ok in EVENTS:
    monitor.record(timestamp, ok)

print("Asking the same monitor the same question at three different moments:\n")
print("```python")
print(f"{'now':>6}  {'in window':>9}  {'error_rate':>10}  should_alert")
for now in (15.0, 65.0, 80.0):
    rate = monitor.error_rate(now)
    print(f"{now:>6}  {len(monitor.events):>9}  {rate:>10.3f}  {monitor.should_alert(now)}")
print("```\n")

print("Reading that: nothing is scheduled and nothing expires on a timer. The window is\n"
      "recomputed whenever somebody looks, which is why the same events give three answers.\n"
      "\n"
      "At t=15 all 8 events are inside the 60s window, 2 of them failed, so 25% — over the 10%\n"
      "threshold with enough traffic to be meaningful, and it pages.\n"
      "\n"
      "At t=65 the five successes from t=0-4 have aged out. What's left is 2 failures and 1\n"
      "success: 67%, a far worse rate, and it does NOT page. Only 3 requests remain, below\n"
      "min_requests=5. That floor is the difference between a real signal and being woken at\n"
      "3am because the single health check that ran all night happened to fail.\n"
      "\n"
      "At t=80 everything has expired: no requests, so no errors, and 0.0 rather than a crash.\n")

print("## The same structure as a rate limiter\n")
print("`SlidingWindowRateLimiter(limit=3, window_seconds=10)`, two clients sharing it:\n")
print("```python")
limiter = reference.SlidingWindowRateLimiter(limit=3, window_seconds=10)
calls = [
    ("alice", 0.0), ("alice", 1.0), ("alice", 2.0), ("alice", 3.0),
    ("bob", 3.0),
    ("alice", 11.0),
]
for client, now in calls:
    allowed = limiter.allow(client, now)
    print(f"allow({client!r:>8}, now={now:>5})  -> {allowed}")
print("```\n")

print("Reading that: alice's first three go through and the fourth is refused, because `limit=3`\n"
      "means the third is the last one allowed. bob is unaffected at the same instant — each\n"
      "client gets its own queue, so one noisy caller can't throttle everyone else.\n"
      "\n"
      "By t=11 alice's earliest hits have slid out of the 10s window, so she's allowed again.\n"
      "The refused call at t=3 was never recorded: if rejections counted, a client retrying in\n"
      "a tight loop would keep its own window permanently full and lock itself out forever.\n")

print("## The variant: a token bucket instead\n")
print("`TokenBucket(rate_per_sec=1, capacity=3)` — starts full, so a new client isn't throttled:\n")
print("```python")
bucket = variant_reference.TokenBucket(rate_per_sec=1, capacity=3)
steps = [
    (0.0, 1, "three in a burst"),
    (0.0, 1, ""),
    (0.0, 1, ""),
    (0.0, 1, "bucket empty"),
    (2.0, 2, "2s later: 2 tokens minted, and this call costs 2"),
    (1.0, 1, "clock jumps BACKWARDS"),
    (4.0, 1, "forward again"),
]
for now, cost, note in steps:
    allowed = bucket.allow(now, cost=cost)
    comment = f"   # {note}" if note else ""
    print(f"allow(now={now:>4}, cost={cost})  -> {str(allowed):<5}  tokens left: {bucket.tokens:.1f}{comment}")
print("```\n")

print("Reading that: the burst is the point. A token bucket lets three requests through at\n"
      "once and then smooths to one per second, which matches how traffic actually arrives.\n"
      "Refilling is lazy — a number multiplied by elapsed time on the next call — so there's no\n"
      "background thread and no timer, and an idle client can't accumulate unlimited credit\n"
      "because the total is capped at capacity.\n"
      "\n"
      "The backwards clock is the case worth remembering. NTP steps and VM migrations really do\n"
      "move the clock, and a naive `now - last` would mint negative tokens or, worse, pay out\n"
      "the same interval twice on the way back up. Here it grants nothing and keeps the latest\n"
      "time it has seen. In production you'd feed it `time.monotonic()`, which cannot go back.\n")

print("Each key gets its own bucket, `KeyedLimiter(rate_per_sec=1, capacity=2)`:\n")
print("```python")
keyed = variant_reference.KeyedLimiter(rate_per_sec=1, capacity=2)
for key, now in [("tenant-a", 0.0), ("tenant-a", 0.0), ("tenant-a", 0.0), ("tenant-b", 0.0)]:
    print(f"allow({key!r}, now={now})  -> {keyed.allow(key, now)}")
print("```\n")

print("Reading that: tenant-a exhausts its own bucket and tenant-b is untouched. The defaultdict\n"
      "factory is what makes that true; handing every key the same pre-built bucket is the bug\n"
      "that lets one tenant rate-limit the entire estate.")
