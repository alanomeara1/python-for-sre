# 12 · Metrics endpoint: Prometheus counters, timing, /metrics and /healthz

**Why this drill:** every service you'll own exposes `/metrics` and `/healthz`. Writing a tiny
version from the stdlib shows you know what the Prometheus client library does for you: label
sets, thread safety, the text format. It also shows what a *good* health check means, which is a
favourite SRE Manager discussion.

## The task, as an interviewer would say it

> Without pulling in prometheus_client, give this batch service a `/metrics` endpoint Prometheus can
> scrape and a `/healthz` endpoint the load balancer can use. I want labelled counters, a way to time a
> block of code, and health checks for dependencies: if any check fails, return 503 and say which.

```python
metrics = Metrics()
metrics.inc("http_requests_total", {"path": "/", "code": "200"})
with timed(metrics, "job_seconds"):
    run_job()

server = make_server(metrics, checks={"db": db.ping, "disk": lambda: disk_free() > 0.1})
server.serve_forever()
```

`GET /metrics`:

```
# TYPE http_requests_total counter
http_requests_total{code="200",path="/"} 2.0
http_requests_total{code="500",path="/api"} 1.0
# TYPE job_seconds summary
job_seconds_sum 0.75
job_seconds_count 2
```

## Contract (what the tests call)

```python
class Metrics:
    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1) -> None
        # value < 0 -> ValueError (counters only go up)
    def observe(self, name: str, seconds: float) -> None
        # accumulates <name>_sum and <name>_count
    def render(self) -> str
        # Counters first, sorted by (name, labels); then summaries sorted by name.
        # One "# TYPE <name> counter|summary" line before each metric name's samples.
        # Labels sorted by key: name{a="1",b="2"}; no braces when there are no labels.
        # Counter values and _sum rendered with repr(float(v)) -> "2.0", "0.75"; _count as an int.
        # Label values escape \ as \\, " as \", newline as \n. Output ends with "\n".
        # Must be safe to call from many threads at once.

@contextmanager
def timed(metrics: Metrics, name: str)
    # observe the elapsed time (time.perf_counter) even if the block raises

def make_server(metrics: Metrics, checks: dict[str, Callable[[], bool]],
                host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer
    # GET /metrics -> 200, Content-Type "text/plain; version=0.0.4", body = metrics.render()
    # GET /healthz -> 200 {"status": "ok"} when every check returns truthy
    #              -> 503 {"status": "fail", "failed": [sorted names]} otherwise
    #                 a check that RAISES counts as failed. It never becomes a 500.
    # anything else -> 404
    # The server is returned NOT started; the caller runs serve_forever().
```

## Patterns you are drilling

- `with self._lock:` around every read and write of shared dicts
- Turning an unhashable `dict` of labels into a key: `tuple(sorted(labels.items()))`
- `@contextmanager` + `start = time.perf_counter()` + `try: yield / finally: observe(...)`
- `BaseHTTPRequestHandler.do_GET`, `send_response`, `send_header`, `end_headers`, `wfile.write(bytes)`
- A handler class defined inside a factory function, so it can close over `metrics` and `checks`
- `ThreadingHTTPServer(("127.0.0.1", 0), Handler)` then `server.server_address[1]` for the real port

## Say this out loud (what the interviewer listens for)

- "The lock matters. `+=` on a dict entry is read-modify-write, and the HTTP server renders on
  another thread while workers increment."
- "`perf_counter`, not `time.time()`: it's monotonic, so an NTP step can't give me a negative duration."
- "A check that throws is a failure. A health endpoint that 500s is indistinguishable from the app
  being broken, and the LB would do the same thing anyway, but I want the body to say *which* dependency."
- The manager-level point: "Be careful what goes in liveness vs readiness. If the DB is down and
  liveness fails, Kubernetes restarts every pod at once and you've turned a DB blip into a full outage.
  Dependencies belong in readiness. Liveness should only fail if this process is wedged."
- "Label cardinality: never put user IDs or raw URLs in labels. Each unique combination is a new
  time series in Prometheus."

## Traps

- `labels` as a mutable default argument `labels={}`: use `None`.
- `wfile.write(str)`: it needs `bytes`, so `.encode()`.
- Forgetting `Content-Length` or `end_headers()`, which leaves the client hanging.
- `timed` without `try/finally` loses the observation on exactly the slow, failing calls you care about.
- `BaseHTTPRequestHandler` logs every request to stderr. Override `log_message` (or route it to logging).
