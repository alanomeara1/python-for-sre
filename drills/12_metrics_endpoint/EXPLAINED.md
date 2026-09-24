# 12 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

---

## The mental model

Three pieces that barely know about each other:

```
Metrics          thread-safe store  ->  inc() / observe() write, render() reads a snapshot
timed()          a context manager that turns "how long did this take" into observe()
make_server()    an HTTP shell: /metrics serves render(), /healthz runs the checks
```

**Why this shape.** The store knows nothing about HTTP, so you can unit-test it without a socket.
The server knows nothing about how metrics are stored, so it's ten lines of plumbing. That
separation is what makes the whole thing fit in 100 lines and is itself part of what's being marked.

The thing that makes it *hard* is that these run on different threads: workers call `inc()` while
the server thread calls `render()`. Everything below follows from that.

**Memory hook: store, timer, shell. One lock, one snapshot, two routes.**

---

## Chunk 1: `_escape` and why the order matters

```python
def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
```

The exposition format puts label values in double quotes, so three characters need escaping:
backslash, quote, newline.

**Backslash must be replaced first.** If you escaped quotes first, `"` would become `\"`, and the
backslash rule running afterwards would turn that into `\\"` — double-escaped, and wrong. Escaping
the escape character first is the general rule for any encoder you ever write.

`test_label_values_are_escaped` feeds in `say "hi"\now\nplease` (a real backslash *and* a real
newline) precisely to catch the wrong order.

---

## Chunk 2: `Metrics.__init__`

```python
        self._lock = threading.Lock()
        self._counters = defaultdict(float)      # (name, sorted label tuple) -> value
        self._summaries = {}                     # name -> [sum, count]
```

- **`defaultdict(float)`** means a missing series reads as `0.0`, so `+=` needs no setup — the same
  trick as `Counter`, but for floats.
- **Counters and summaries are separate dicts** because they render differently: a counter is one
  sample, a summary is two (`_sum` and `_count`).
- **`[sum, count]` is a list, not a tuple**, because it's mutated in place.

---

## Chunk 3: `inc`, and the label-set key

```python
    def inc(self, name, labels=None, value=1):
        if value < 0:
            raise ValueError("counters only go up")
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._counters[key] += value
```

### Why `labels=None` and not `labels={}`

Default arguments are evaluated **once, at function definition**. A `{}` default is one dict shared
by every call for the life of the process, so anything that mutated it would leak between callers.
`None` plus `labels or {}` is the standard fix, and interviewers do look for it.

### Why the key is `(name, tuple(sorted(items)))`

A dict is mutable and therefore unhashable, so it can't be a dict key at all. Converting to a tuple
makes it hashable. **Sorting** makes `{"path": "/", "code": "200"}` and `{"code": "200", "path": "/"}`
produce the *same* key, which is correct: in Prometheus, label order carries no meaning, so those
are one series, not two.

### Why `value < 0` raises

A counter that can go down isn't a counter. Every consumer — `rate()`, `increase()`, your alerts —
assumes monotonic growth, and a decrease is read as a reset. Rejecting it at the door beats
debugging an impossible graph later. (Use a gauge for values that move both ways.)

### Why the lock

`self._counters[key] += value` is **read-modify-write**: load the current value, add, store it back.
Two threads can both load `7`, both store `8`, and one increment vanishes. The GIL doesn't save you,
because it can be released between bytecodes. `test_inc_is_thread_safe` runs 8 threads × 5000
increments and demands exactly 40000.

---

## Chunk 4: `observe`

```python
        with self._lock:
            totals = self._summaries.setdefault(name, [0.0, 0])
            totals[0] += seconds
            totals[1] += 1
```

`setdefault` fetches the existing list or installs a fresh `[0.0, 0]` and returns it, in one step,
so there's no "check then insert" gap for another thread to slip through.

Keeping `_sum` and `_count` — rather than every individual duration — is what a Prometheus *summary*
does, and it's why metrics are cheap: fixed memory per series no matter how many observations. The
cost is that you can't compute a true percentile from it afterwards; for that you need a histogram
with buckets. Worth saying out loud, because "why not just store all the latencies?" is the obvious
follow-up.

---

## Chunk 5: `render`, snapshot then format

```python
        with self._lock:                         # snapshot under the lock, format outside it
            counters = sorted(self._counters.items())
            summaries = sorted((name, list(t)) for name, t in self._summaries.items())
```

### Why snapshot and release, rather than hold the lock throughout

Formatting is string work — slow compared with an increment. Holding the lock while you build the
whole document would block every worker thread in the process on every scrape. Copy fast, release,
then take your time.

### Why `list(t)`

`self._summaries[name]` is a *mutable* list. Copying the reference alone would leave the "snapshot"
pointing at live data that worker threads keep mutating while you format it. `list(t)` copies the
two numbers, so the snapshot is genuinely frozen.

### Why sorted

Deterministic output. It makes the endpoint diffable, makes `test_render_exact_format` possible, and
means a scrape doesn't reshuffle between requests. Sorting `(name, labels)` tuples also groups every
series of one metric family together, which the next part relies on.

### The rendering loop

```python
        for (name, labels), value in counters:
            if name != last_name:
                lines.append(f"# TYPE {name} counter")
                last_name = name
            label_part = ""
            if labels:
                label_part = "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels) + "}"
            lines.append(f"{name}{label_part} {float(value)!r}")
```

- **`# TYPE` once per metric family**, not per sample. The format wants it before the family's first
  sample, and `last_name` tracks that. This only works because the list is sorted by name.
- **No braces at all when there are no labels** (`jobs_total 1.0`, not `jobs_total{} 1.0`). Empty
  braces are technically accepted by most parsers, but the canonical form omits them.
- **`float(value)!r`** renders `2` as `2.0`. `!r` is `repr()`, which for floats gives the shortest
  string that round-trips back to the same value. Counter values are floats by convention, while
  `_count` is rendered as a plain int — which is why the two are formatted differently.
- **`"\n".join(lines) + "\n"`**: the format requires a trailing newline, and joining is how you get
  exactly one separator between lines rather than a stray one at the end.

---

## Chunk 6: `timed`

```python
@contextmanager
def timed(metrics: Metrics, name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        metrics.observe(name, time.perf_counter() - start)
```

- **`@contextmanager`** turns a generator into a context manager: everything before `yield` is the
  setup, the `yield` is where the `with` block runs, everything after is the teardown.
- **`try/finally` is the whole point.** Without it, an exception in the block skips the `observe`,
  so you lose timings for exactly the slow, failing calls you most want to see. The failure mode is
  cruel: your latency graph looks *better* during an incident.
- **`perf_counter`, not `time.time()`.** `perf_counter` is monotonic and high-resolution. Wall-clock
  time can step backwards (NTP correction, a VM resuming, a manual clock change), which yields a
  *negative* duration and poisons the sum. Any time you measure an elapsed duration rather than a
  point in time, reach for `perf_counter` or `monotonic`.

---

## Chunk 7: health checks that fail closed

```python
def _passes(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:
        return False
```

**A check that raises is a failed check, never a 500.** Two reasons, and both are worth saying:

1. A 500 from `/healthz` is indistinguishable from the health endpoint itself being broken. You lose
   the body that names *which* dependency is down, which is the entire diagnostic value.
2. The load balancer treats 500 and 503 identically anyway, so raising buys nothing and costs
   information.

`except Exception` rather than bare `except:` so `KeyboardInterrupt` and `SystemExit` still work.

### The manager-level point

Put dependency checks in **readiness**, not liveness. If the database is down and your *liveness*
probe fails, Kubernetes restarts every pod simultaneously, and you've turned a database blip into a
full outage with a cold cache. Liveness should fail only when *this process* is wedged. This is the
discussion the drill is really preparing you for.

---

## Chunk 8: `make_server`

```python
def make_server(metrics, checks, host="127.0.0.1", port=0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ...
    return ThreadingHTTPServer((host, port), Handler)
```

- **The handler class is defined inside the function** so it can close over `metrics` and `checks`.
  You can't pass constructor arguments, because the server instantiates a fresh handler *per
  request*. A closure is the idiomatic workaround (a class attribute set afterwards is the other).
- **`ThreadingHTTPServer`, not `HTTPServer`:** one thread per request, so a slow health check can't
  block a scrape. It's also the reason `Metrics` needs its lock — the concurrency you chose here
  creates the hazard you handled there.
- **`port=0` lets the OS pick a free port**, and `server.server_address[1]` tells you which. Tests
  then never collide with each other or with something already running on a fixed port.
- **Returned unstarted.** The caller owns the lifecycle: tests run `serve_forever` in a daemon
  thread and call `shutdown()`; production calls it directly. A function that both builds *and*
  blocks would be untestable.

### `_send`

```python
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
```

- **`.encode()`** because `wfile` is a *binary* stream; writing a `str` raises `TypeError`.
- **`Content-Length`** computed from the encoded bytes, not `len(body)` — they differ the moment
  any non-ASCII appears. Omit the header and a keep-alive client waits for an EOF that never comes.
- **`end_headers()`** sends the blank line that separates headers from body. Forget it and the
  client hangs.
- **`log_message` overridden to do nothing**, because the default writes a line to stderr for every
  request. Prometheus scrapes every 15 seconds; that's 5,760 junk lines a day per target.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_render_exact_format` | `# TYPE` emitted per sample instead of per family, output not sorted, braces on an unlabelled metric, or a missing trailing newline |
| `test_inc_value_and_rejects_negative` | no `ValueError` on a negative, or the value rendered as `1024` instead of `1024.5`/float form |
| `test_label_values_are_escaped` | escaped quotes before backslashes, so the backslashes got double-escaped |
| `test_inc_is_thread_safe` | no lock around the `+=`: you'll be a few hundred short of 40000, and it won't fail every time |
| `test_timed_observes_duration` | used `time.time()`, or observed the wrong name, or measured outside the block |
| `test_timed_records_even_when_block_raises` | no `try/finally` around the `yield` |
| `test_metrics_endpoint` | wrong Content-Type (it must be `text/plain; version=0.0.4`), or body not encoded |
| `test_healthz_ok` | returned the wrong JSON shape, or ran the checks at server-build time instead of per request |
| `test_healthz_failing_and_raising_checks` | a raising check produced a 500, or `failed` wasn't sorted |
| `test_unknown_path_is_404` | no final `else` branch |

If the whole test file hangs, the server never sent `end_headers()` or `Content-Length`, and the
client is waiting.

---

## The variant: what actually changes

Consuming the format instead of producing it. Four differences worth understanding:

1. **You cannot split labels on commas.** `path="/a,b"` is legal, and so is an escaped quote inside
   a value. The label regex has to understand quoted strings:
   `"(?:[^"\\]|\\.)*"` means "any run of characters that are neither a quote nor a backslash, or an
   escaped pair". Reaching for `.split(",")` here is the trap the test
   (`test_parse_commas_spaces_and_escaped_quotes_in_values`) is built to catch.

2. **Unescaping must be one pass, not chained `.replace()` calls.** Replacing `\\` first and `\n`
   second turns the two-character sequence *backslash-n* into a newline when the input actually
   meant a literal backslash followed by `n`. `re.sub(r"\\(.)", ...)` walks each escape pair exactly
   once, which is the only correct way to reverse an escaping scheme.

3. **Labels become a `frozenset`, not a sorted tuple.** Both are hashable; a frozenset is
   *order-independent by construction*, which suits parsing where you're reading whatever order the
   exporter chose. (The main drill sorts a tuple instead — same goal, different tool.)

4. **Counter resets are the real content of `counter_rate`.** When `curr < prev`, the process
   restarted and the counter began again at zero, so the increase is `curr` itself, not a negative
   number. This is exactly what PromQL's `rate()` does. Skip it and every pod restart produces a
   huge negative rate that breaks alerting on that series. Series present in only one scrape have no
   baseline, so they're skipped rather than guessed at.

Say this one out loud: **"never put user IDs or raw URLs in labels."** Every distinct label
combination is a separate time series, and unbounded cardinality is the classic way to take down
your own Prometheus.
