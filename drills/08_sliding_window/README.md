# 08 · Sliding windows: error-rate alert and rate limiter

**Why this drill:** "Alert if the error rate over the last 60 seconds goes above 5%" and "design
a rate limiter" are two of the most-asked SRE coding questions. They're the same data structure:
a time-ordered deque you trim from the left. Learn the shape once and both questions are routine.

## The task, as an interviewer would say it

> Part 1: We get a stream of request results with timestamps. Build a monitor that can tell me
> the error rate over the last N seconds at any moment, and whether we should alert. Don't page
> on 1 failure out of 1 request.
>
> Part 2: Build a per-client rate limiter: each client gets at most `limit` requests in any
> rolling `window_seconds`.

## Contract (what the tests call)

```python
class ErrorRateMonitor:
    def __init__(self, window_seconds: float, threshold: float, min_requests: int = 1): ...
    def record(self, timestamp: float, ok: bool) -> None: ...     # timestamps arrive in order
    def error_rate(self, now: float) -> float: ...                  # 0.0 when the window is empty
    def should_alert(self, now: float) -> bool: ...
        # True when requests in window >= min_requests AND error_rate >= threshold

class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float): ...
    def allow(self, client_id: str, now: float) -> bool: ...
        # A rejected request does NOT count against the client.
```

**Window rule, for both classes:** an event at time `t` is inside the window at `now` when
`now - window_seconds < t <= now`. At exactly `t + window_seconds`, it has expired.

## Patterns you are drilling

- `collections.deque`: `append` on the right, `popleft` from the left, both O(1)
- Evict-then-answer: every query first drops expired entries from the left
- Keep a **running count** of errors alongside the deque. Never re-scan the window with `sum(...)`.
- `defaultdict(deque)`: one deque per client, created on first use
- Time passed in as `now`, so tests are exact and fast

## Say this out loud (what the interviewer listens for)

- "Each event is appended once and popped once, so it's O(1) amortised per operation and memory is bounded by the window."
- "I maintain the error count incrementally. Summing the deque each call is O(window) and falls over at high QPS."
- "`min_requests` stops a single failed health check at 3am from paging someone."
- "Rejected requests don't count. Otherwise a client that retries in a tight loop locks itself out forever."
- "This is single-process. Across a fleet I'd use Redis (a sorted set per client, or `INCR` with expiry) or push
  limiting to the edge: Envoy, nginx `limit_req`, the API gateway."
- "Sliding log is exact but stores every timestamp. At high volume I'd switch to a token bucket
  (see the variant) or a sliding-window counter, trading exactness for memory."

## Traps

- `while self.events[0]...` without checking the deque is non-empty first gives an `IndexError`.
- `<` vs `<=` at the boundary. Pick one, state it, and be consistent (the tests use the rule above).
- Forgetting to decrement the error count when evicting an error.
- Recording the request *before* checking the limit, so rejected requests fill the window.
- Idle clients leave empty deques in the dict forever. Mention it; drop empty deques if memory matters.
