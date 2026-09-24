# 08 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

---

## The mental model

Both classes in this drill are the same data structure asking different questions:

```
a deque of timestamps, oldest on the left
        ↓                              ↓
ErrorRateMonitor                SlidingWindowRateLimiter
"what fraction failed           "has this client had too many
 in the last N seconds?"         in the last N seconds?"
```

Every operation has the same two beats: **evict from the left, then answer.** Old entries leave
from the left because they're the oldest; new entries arrive on the right. That's exactly what a
deque is for: `popleft()` and `append()` are both O(1), where a list's `pop(0)` is O(n) because
every remaining element shifts down one slot.

**Memory hook: append right, evict left, then answer.**

The one non-obvious addition is the **running error count**. You keep a separate integer, updated
on the way in and on the way out, so answering never re-reads the window.

---

## Chunk 1: The monitor's state

```python
class ErrorRateMonitor:
    def __init__(self, window_seconds: float, threshold: float, min_requests: int = 1):
        self.window = window_seconds
        self.threshold = threshold
        self.min_requests = min_requests
        self.events: deque[tuple[float, bool]] = deque()   # oldest on the left
        self.errors = 0                                    # running count, never re-scan
```

**Why store `(timestamp, ok)` pairs:** eviction needs the time, and the error count needs to know
whether the thing leaving was a failure. Two parallel deques would need to stay in lockstep;
one deque of tuples can't drift.

**Why a separate `self.errors` counter:** this is the point of the drill. The obvious
implementation answers `error_rate` with `sum(1 for t, ok in self.events if not ok)`, which walks
the whole window on every call: O(window) per query. At 10k requests per second with a 60-second
window that's 600k iterations *per query*. Keeping a running count makes it O(1), and the test
`test_monitor_is_fast_at_volume` (100,000 record-and-query cycles under 2 seconds) fails the
re-scanning version by a wide margin.

The trade is that the counter must be maintained in **two** places: incremented in `record`,
decremented in `_evict`. Forgetting the decrement is the classic bug, and it shows up as an error
rate that only ever climbs. There's a test for it.

**Why `min_requests` exists at all:** without it, the first failed request of a quiet night is a
100% error rate, and someone gets paged at 3am because one health check missed. It's a statistical
significance floor, and it's the kind of detail that marks out someone who has carried a pager.

---

## Chunk 2: `record` and `_evict`

```python
    def record(self, timestamp: float, ok: bool) -> None:
        self.events.append((timestamp, ok))
        if not ok:
            self.errors += 1
```

**Why `record` doesn't evict:** eviction depends on "now", and a recorded event doesn't tell you
what time it is now. Every *query* evicts first, so the window is always correct at the moment
anyone looks at it. Recording stays O(1) and trivially correct.

```python
    def _evict(self, now: float) -> None:
        # An event at t is in the window while now - window < t, so evict t <= now - window.
        cutoff = now - self.window
        while self.events and self.events[0][0] <= cutoff:
            _, ok = self.events.popleft()
            if not ok:
                self.errors -= 1
```

**Why `while self.events and ...` in that order:** `and` short-circuits, so the emptiness check
must come first. Reversing it gives `IndexError: deque index out of range` the moment the window
drains completely, which is the easiest bug to write here and the one the boundary test catches.

**Why `while` and not `if`:** a single query can expire many events at once, for instance after an
idle gap. One `if` would leave stale entries in the window and quietly skew the rate.

**Why the leading underscore:** `_evict` is internal. The public surface is `record`,
`error_rate`, `should_alert`. It's a convention, not enforcement, and it tells a reader which
methods they're allowed to depend on.

**Why `<=` on the cutoff:** the boundary rule is `now - window < t <= now`, so an event at exactly
`t + window` has expired. `<=` in the eviction implements that. The rule itself is arbitrary,
and *either* convention is defensible. What isn't defensible is being inconsistent between the two
classes, or not knowing which you chose. State it, then implement it exactly:
`m.record(0, ok=False)` with a 60-second window is gone at `now=60` and present at `now=59.9`.

**Rebuild it from first principles:** "in the last N seconds" means `t > now - N`. Negate that for
what to throw away: `t <= now - N`. Everything else follows.

---

## Chunk 3: Answering

```python
    def error_rate(self, now: float) -> float:
        self._evict(now)
        return self.errors / len(self.events) if self.events else 0.0

    def should_alert(self, now: float) -> bool:
        rate = self.error_rate(now)                        # evicts first
        # Don't page on 1 failure out of 1 request.
        return len(self.events) >= self.min_requests and rate >= self.threshold
```

**Why evict at the top of the query:** it's the only place "now" exists. This is the
evict-then-answer discipline, and doing it anywhere else leaves a window that is correct only by
luck.

**Why the empty guard:** same divide-by-zero lesson as drill 01. An empty window means no requests,
which means a 0.0 error rate, not a crash. Note `len(deque)` is O(1), so this costs nothing.

**Why `should_alert` calls `error_rate` rather than re-implementing it:** one eviction, one
definition of the rate, and the `len(self.events)` read afterwards is accurate because the
eviction has already happened. Order matters: reading the length *before* calling `error_rate`
would count expired events.

**Why `>=` for both thresholds:** "alert at 10%" should fire at exactly 10%. The test pins this:
1 error in 10 requests with a 0.1 threshold alerts, and 1 in 11 does not.

---

## Chunk 4: The rate limiter

```python
class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self.hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, client_id: str, now: float) -> bool:
        hits = self.hits[client_id]
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            return False              # rejected requests are not recorded
        hits.append(now)
        return True
```

**Why `defaultdict(deque)`:** a new client's first request would otherwise need
`if client_id not in self.hits: self.hits[client_id] = deque()`. `defaultdict` calls the factory
on first access. Note you pass `deque` itself, not `deque()`: the factory is called per missing
key, so every client gets their own. Passing an already-built `deque()` would share one queue
between every client, which is the same class of bug as the `defaultdict(lambda: one_bucket)`
mistake in the variant.

**Why only timestamps here, no tuples:** a rate limiter doesn't care about success or failure, so
there's nothing to pair with the time.

**Why `len(hits) >= self.limit` and not `>`:** `limit=3` means the third request is allowed and the
fourth is not. With `>`, you'd permit `limit + 1`, an off-by-one that only shows up under load.

**Why rejected requests aren't recorded:** this is the operationally important decision. If a
rejection appended to the deque, a client retrying in a tight loop would keep refilling its own
window and stay locked out forever, long after it stopped exceeding the real limit. Recording only
admitted requests means the limiter measures what you actually served. The test hammers a limited
client four times and then checks it's allowed again exactly when the *served* requests expire.

**Why the local `hits` variable:** `self.hits[client_id]` is a dict lookup plus a possible factory
call. Binding it once is both faster and easier to read than repeating it five times.

**What to volunteer about the limits of this design:** it's single-process, so a fleet of ten API
servers enforces ten times the limit. Across hosts you'd use Redis (a sorted set per client, or
`INCR` with an expiry) or push limiting to the edge (Envoy, nginx `limit_req`, the API gateway).
Memory is bounded by the window *per client*, but idle clients leave empty deques in the dict
forever, so a long-running process wants periodic pruning. Saying this unprompted is worth more
than the code.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_error_rate_basic` | not dividing errors by the number of events, or evicting with the wrong sign |
| `test_events_expire_at_window_boundary` | `<` instead of `<=` in `_evict`, so an event outlives its window by an instant |
| `test_error_count_decrements_on_eviction` | you increment `self.errors` in `record` but never decrement it in `_evict` |
| `test_should_alert_respects_threshold_and_min_requests` | used `>` rather than `>=`, or read `len(self.events)` before evicting |
| `test_monitor_is_fast_at_volume` | you re-scan the deque per query (`sum(...)`) instead of keeping a running count |
| `test_rate_limiter_limit_and_window` | off-by-one (`>` instead of `>=`), or the boundary sign again |
| `test_rate_limiter_clients_are_independent` | one shared deque instead of `defaultdict(deque)` |
| `test_rejected_requests_do_not_count` | you append to the deque before checking the limit |

`IndexError: deque index out of range` means you checked `events[0]` before checking the deque is
non-empty.

---

## The variant: what actually changes

A token bucket answers the same question with two floats instead of a queue of timestamps. Five
ideas worth understanding:

1. **State is two numbers, not a list.** `tokens` and `last`. Memory per client is constant
   regardless of traffic, where the sliding log grows with the number of requests in the window.
   The trade is exactness: a bucket permits a burst up to `capacity` and then smooths to `rate`,
   while a sliding log enforces "at most N in any window" precisely. That comparison is the
   follow-up question interviewers ask, so have the sentence ready.

2. **Lazy refill.** There is no background thread topping buckets up. When `allow` is called you
   work out how much time has passed and mint that many tokens:
   `tokens = min(capacity, tokens + elapsed * rate)`. O(1) per call, no timers, no scheduler. The
   `min` is what caps a long idle period from granting unlimited burst.

3. **New buckets start full.** A brand-new client shouldn't be throttled on its first request.
   Starting empty would rate-limit everyone at exactly the moment they arrive.

4. **Clocks go backwards, and the guard is in two halves.** NTP steps, VM migrations and
   leap-second smearing can all hand you a `now` earlier than the last one you saw.
   `elapsed = max(0.0, now - self.last)` stops a negative elapsed from *draining* the bucket, and
   `self.last = max(self.last, now)` keeps the latest time seen, so that when the clock jumps
   forward again you don't pay out the same interval twice. Two tests cover the two halves
   separately, because each guard fixes a different bug. The deeper point to say out loud: in
   production you'd use `time.monotonic()`, which cannot go backwards; the guard is for when the
   caller hands you wall-clock time.

5. **`defaultdict(lambda: TokenBucket(rate, capacity))`, not `defaultdict(TokenBucket)`.** The
   factory takes no arguments, so you need the lambda to close over the settings, and the lambda
   builds a *new* bucket per key. Writing `shared = TokenBucket(...)` then
   `defaultdict(lambda: shared)` hands every client the same bucket, and one noisy client
   throttles everyone.

Also worth noticing: a rejected request consumes nothing (same principle as the sliding window),
and a request costing more than `capacity` can *never* succeed, however long you wait. Reject that
at the API layer with a clear error rather than letting the caller retry forever.
