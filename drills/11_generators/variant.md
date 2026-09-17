# 11 · Variant: bounded-memory aggregation of an event stream

Same patterns as the main drill (lazy generators, single pass, itertools), aimed at aggregation
instead of transport.

## The task

> We've got a firehose of events: millions a minute, too many to hold. Give me three things: the
> top K values of any field (top endpoints, top customers), a syslog-style "last message repeated
> N times" collapse, and a per-bucket count for a time series, all in one pass.

```python
events = [{"path": "/api", "user": "a"}, {"path": "/login", "user": "b"}, {"path": "/api", "user": "a"}]
top_k(events, 1, "path")                           # -> [("/api", 2)]

list(dedupe_consecutive(["boom", "boom", "ok", "boom"]))
# -> [("boom", 2), ("ok", 1), ("boom", 1)]

list(window_counts([0, 5, 59, 60, 61, 185], 60))
# -> [(0, 3), (60, 2), (180, 1)]
```

## Contract

```python
def top_k(events: Iterable[dict], k: int, key: str) -> list[tuple[object, int]]
    # most common values of event[key], highest count first.
    # Ties: the value seen FIRST in the stream comes first.
    # Events missing the key are ignored. Use heapq.nlargest.

def dedupe_consecutive(lines: Iterable[str]) -> Iterator[tuple[str, int]]
    # collapse runs of identical adjacent lines into (line, run_length). Lazy. Use itertools.groupby.

def window_counts(timestamps: Iterable[float], bucket_seconds: int) -> Iterator[tuple[int, int]]
    # timestamps are epoch seconds in non-decreasing order.
    # yield (bucket_start, count) for each non-empty bucket, as soon as the bucket is complete
    # (i.e. when a timestamp from a later bucket arrives, or the input ends).
    # A timestamp older than the current bucket -> ValueError (out-of-order input).
    # bucket_start is an int: floor(ts / bucket_seconds) * bucket_seconds.
```

## Say this out loud

- "`top_k` memory is O(distinct keys), not O(events). If cardinality is unbounded, like user IDs on a
  public API, I'd switch to an approximate sketch (Count-Min, or HyperLogLog for distinct counts)."
- "`heapq.nlargest(k, ...)` is O(n log k), better than a full sort when k is small, and it's stable
  on ties, which makes the output deterministic."
- "`window_counts` only holds the current bucket, so it yields as it goes and works on an infinite
  stream. That's the core of every metrics pipeline."
- "I raise on out-of-order data instead of silently miscounting. Real pipelines handle late events with
  a watermark and allowed lateness."
