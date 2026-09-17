# 08 · Variant: token bucket rate limiter

Same problem as part 2 of the main drill, different algorithm. Interviewers often ask for
this one by name, and follow up with "what's the difference from a sliding window?"

## The task

> Implement a token bucket. It refills at `rate_per_sec` tokens per second up to `capacity`.
> A request costing `cost` tokens is allowed if that many tokens are available. Then give
> every API key its own bucket. Oh, and our hosts have had NTP jumps, so time can go backwards.

## Contract

```python
class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float): ...
    def allow(self, now: float, cost: float = 1) -> bool: ...

class KeyedLimiter:
    def __init__(self, rate_per_sec: float, capacity: float): ...
    def allow(self, key: str, now: float, cost: float = 1) -> bool: ...
```

- A new bucket starts **full**. A brand-new client shouldn't be throttled on its first request.
- Refill is **lazy**: compute tokens from elapsed time when `allow` is called. There's no background thread.
- Tokens never exceed `capacity`.
- If `now` is earlier than the latest time seen, grant **no** tokens, and don't let the backwards
  jump cause extra tokens later either. Remember the *latest* time, not the most recent call's time.
- A rejected request consumes nothing.

## Say this out loud

- "Lazy refill means O(1) per call and no timers: `tokens = min(capacity, tokens + elapsed * rate)`."
- "Token bucket allows bursts up to `capacity`, then smooths to `rate`. A sliding log is exact but stores
  every timestamp. The bucket stores two floats per client."
- "I take `now` as a parameter. In production I'd use `time.monotonic()`, which can't go backwards,
  and wall clock can. The backwards guard is for when the caller hands me wall-clock time."
- "`defaultdict(lambda: TokenBucket(...))` builds a bucket per key on first use. `defaultdict(lambda: one_bucket)` would
  share a single bucket between everyone. That's a classic bug."
- "A request costing more than `capacity` can never succeed. I'd reject it at the API layer with a clear error."
