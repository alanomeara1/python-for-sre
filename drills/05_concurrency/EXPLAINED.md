# 05 · Explained: how and why, line by line

Read this in the Study step, and come back whenever you're stuck. `reference.py` shows you *what* to
write. This file is *why* it's written that way, so you can rebuild it instead of fishing for a memory.

---

## The mental model

```
check_endpoint(url, timeout)     check ONE thing, and never raise
check_endpoints(urls, ...)       run that function many times at once, and never lose a result
```

**Why this split matters more than usual:** all the error handling lives in the inner function, so the
concurrency layer has nothing to think about except scheduling and collecting. If you try to do both
jobs in one function you end up with a `try` inside a `with` inside a loop, and it becomes unreadable.

**Memory hook: one checker, one pool, one dict.**

The deeper idea: **isolation.** A batch of 500 checks where one host blackholes must still return 499
results. Every design decision below serves that.

---

## Chunk 1: `check_endpoint`

```python
def check_endpoint(url: str, timeout: float) -> dict:
    start = time.monotonic()
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        return {"ok": False, "status": None, "latency": time.monotonic() - start,
                "error": f"{type(exc).__name__}: {exc}"}
```

- **`time.monotonic()` around the call** gives you latency that can't go negative when NTP adjusts the
  wall clock mid-check. Started before the `try` so the timer covers DNS, connect and read.
- **`requests.RequestException` is the base class** of everything requests raises: `ConnectionError`,
  `Timeout`, `TooManyRedirects`, `MissingSchema`. One clause covers them all, while a `TypeError` from
  your own code still escapes and gets noticed.
- **It returns instead of raising.** That's the contract that makes the pool layer simple.
- **`type(exc).__name__`** gives `ConnectionError` rather than the full repr. Short enough for a table,
  specific enough to act on. `test_check_endpoint_connection_refused` asserts that prefix.
- **`status: None` on a transport failure.** There *was* no HTTP response, so a status would be a lie.
  `None` is the honest value, and it distinguishes "couldn't reach it" from "it answered 500".
- **`timeout=timeout` again.** Without it, one blackholed host holds a worker thread forever, and at
  500 URLs your pool is permanently full.

```python
    ok = response.status_code < 400
    return {"ok": ok, "status": response.status_code, "latency": time.monotonic() - start,
            "error": None if ok else f"HTTP {response.status_code}"}
```

- **`< 400` counts 2xx and 3xx as healthy.** A redirect is a working server. Note `requests` follows
  redirects by default, so you'd usually see the final 200 anyway.
- **Every result has the same four keys**, whichever path produced it. Uniform shape means the caller
  never writes `result.get("status")` defensively, and it tabulates cleanly.

---

## Chunk 2: `check_endpoints`

```python
def check_endpoints(urls: list[str], max_workers: int = 10, timeout: float = 2.0) -> dict[str, dict]:
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(check_endpoint, url, timeout): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as exc:
                results[url] = {"ok": False, "status": None, "latency": 0.0,
                                "error": f"{type(exc).__name__}: {exc}"}
    return results
```

### Why threads work here despite the GIL

The GIL stops two threads running Python *bytecode* at once, but a thread waiting on a socket has
already released it. Health checks are almost entirely waiting, so a pool of 10 gives close to a 10×
speedup. Say exactly this in an interview, and add the counterpart: **CPU-bound work needs
`ProcessPoolExecutor`**, because there the GIL really is the bottleneck.

### The four lines that matter

| Line | Why it's written that way |
|---|---|
| `with ThreadPoolExecutor(...) as pool:` | the `with` block waits for every task and tears the threads down. Without it, threads leak, and in a long-running process that's a slow death |
| `pool.submit(check_endpoint, url, timeout)` | pass the function and its arguments **separately**. `pool.submit(check_endpoint(url, timeout))` calls it right there on your thread, runs everything sequentially, and submits the result. It "works", it's just not concurrent |
| `{future: url for url in urls}` | `as_completed` yields futures in *finish* order, so the future is your only handle on which URL it was. The dict is the lookup back |
| `for future in as_completed(futures):` | iterating a dict iterates its keys, which are the futures. Results arrive as they finish, so you could report progress or alert early |

- **`max_workers` is a politeness limit**, not a performance dial. 500 simultaneous connections can
  exhaust file descriptors on your side and look like an attack from the other. Pick it deliberately.
- **`try` around `future.result()`.** `.result()` re-raises whatever the task raised. `check_endpoint`
  shouldn't raise, but if a bug in it ever does, this keeps the other 499 results. This is the single
  most common omission in interview answers.
- **`latency: 0.0` in that fallback** because no meaningful measurement exists: the failure was in your
  code, not the network.
- **Returns a dict keyed by URL.** Worth mentioning: duplicate URLs collapse into one key. Either say
  so or dedupe deliberately.

**Rough maths to quote:** total time ≈ slowest check × (number of URLs / workers). With a per-request
timeout, that bounds the whole run, which is what makes this safe to put in a cron job.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_check_endpoint_ok` | missing a key, or `latency` isn't a float (measure with `time.monotonic()`) |
| `test_check_endpoint_http_error` | `ok` computed with the wrong boundary, or `error` not formatted `HTTP 500` |
| `test_check_endpoint_connection_refused` | you let the exception escape, or `status` isn't `None`, or the error string doesn't start with the exception class name |
| `test_check_endpoint_timeout` | no `timeout=` passed to `requests.get`, so nothing timed out |
| `test_check_endpoints_runs_concurrently` | you called the function instead of submitting it, or built the pool inside the loop. It ran sequentially |
| `test_check_endpoints_respects_max_workers` | `max_workers` ignored (the test asserts one worker really is serial) |
| `test_check_endpoints_one_failure_does_not_break_batch` | no `try` around `future.result()`, so one failure lost the batch |
| `test_check_endpoints_empty` | you assumed at least one URL; an empty list must give `{}` |

---

## The variant: what actually changes

TCP port checks instead of HTTP. The pool code is nearly identical, which is the point: **the pattern
is the transferable thing.** Four differences:

1. **Raw sockets, one layer down.** `socket.create_connection((host, port), timeout=...)` does DNS
   resolution and tries each returned address. It proves a TCP handshake completed; it says nothing
   about whether the service behind the port is healthy. Know which question you're answering.
2. **`with` on the socket.** A socket is a file descriptor, and leaking them in a loop over thousands of
   targets will hit your `ulimit`. `test_check_port_closes_the_socket` exists because this is easy to forget.
3. **`except OSError`** is the equivalent of `requests.RequestException` here: `ConnectionRefusedError`,
   `TimeoutError` and `socket.gaierror` (DNS failure) all subclass it.
4. **Tuple keys.** The results dict is keyed by `(host, port)`, which works because tuples are hashable
   (lists are not). `sorted()` on those tuples then gives host-then-port order for free, which is why
   `summarize` is three lines.

Note the variant's `check_ports` calls `future.result()` **without** a `try`, unlike the main drill.
That's defensible, because `check_port` catches `OSError` itself, but it is a genuine difference in
robustness: a bug inside `check_port` would sink the batch. Worth noticing rather than copying blindly.
