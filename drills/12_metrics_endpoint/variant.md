# 12 · Variant: parse a scrape and compute counter rates

The other side of the main drill: instead of producing Prometheus text, consume it. Same patterns:
regex with named groups, label sets as hashable keys, careful numeric handling.

## The task

> Prometheus is down and I need request rates *now*. Write something that scrapes `/metrics` twice
> and gives me the per-second rate for each counter series. Remember that counters reset to zero when
> a pod restarts.

```python
text = '''
# HELP http_requests_total Total requests.
# TYPE http_requests_total counter
http_requests_total{code="200",path="/"} 1027
http_requests_total{code="500",path="/api"} 3
process_start_time_seconds 1.7265672e+09
'''
parse_exposition(text)
# -> {("http_requests_total", frozenset({("code", "200"), ("path", "/")})): 1027.0,
#     ("http_requests_total", frozenset({("code", "500"), ("path", "/api")})): 3.0,
#     ("process_start_time_seconds", frozenset()): 1726567200.0}
```

## Contract

```python
def parse_exposition(text: str) -> dict[tuple[str, frozenset], float]
    # key: (metric name, frozenset of (label, value) pairs); value: float
    # skip blank lines and lines starting with "#"
    # label values may contain commas, spaces and escaped quotes (\"): parse them properly,
    # and unescape \" -> " and \\ -> \ in the value
    # an optional trailing timestamp after the value is ignored
    # values like "NaN", "+Inf", "1.7e+09" must parse (float() handles them)

def counter_rate(prev: dict, curr: dict, seconds: float) -> dict[tuple[str, frozenset], float]
    # per-second rate for every series present in BOTH scrapes
    # if curr < prev the counter reset (process restarted): the increase is curr, not negative
    # seconds <= 0 -> ValueError
```

## Say this out loud

- "Labels become a frozenset. It's hashable and order-independent, because `{a,b}` and `{b,a}` are the
  same series."
- "I can't split labels on commas. `path=\"/a,b\"` is legal, so the label regex has to understand quoted strings."
- "Reset handling is exactly what PromQL's `rate()` does. Without it a pod restart shows as a huge
  negative rate and breaks every alert on that series."
- "Series in only one scrape have no baseline, so I skip them rather than guess."
