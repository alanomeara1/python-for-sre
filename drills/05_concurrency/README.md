# 05 · Concurrency: check many endpoints with a thread pool

**Why this drill:** "Now do it for 500 hosts" is the standard follow-up to every health-check question.
The interviewer wants `ThreadPoolExecutor`, isolation of per-host failures, and a sentence on why threads
work well for I/O-bound work despite the GIL.

## The task, as an interviewer would say it

> Here's a list of service health URLs. Check them all and give me, per URL: whether it's healthy,
> the status code, the latency, and the error if it failed. There are hundreds, so it can't take
> hundreds of seconds, and one broken host must not break the report.

## Contract (what the tests call)

```python
def check_endpoint(url: str, timeout: float) -> dict
    # {"ok": bool, "status": int | None, "latency": float, "error": str | None}
    # ok = status < 400
    # HTTP 4xx/5xx     -> ok False, status set, error "HTTP <status>"
    # request failed   -> ok False, status None, error "<ExceptionClassName>: <message>"
    # never raises for network problems

def check_endpoints(urls: list[str], max_workers: int = 10, timeout: float = 2.0) -> dict[str, dict]
    # {url: check_endpoint result}, checked concurrently with a ThreadPoolExecutor
```

## Patterns you are drilling

- `with ThreadPoolExecutor(max_workers=n) as pool:`
- `futures = {pool.submit(fn, arg): arg for arg in items}`: the dict maps each future back to its input
- `for future in as_completed(futures): key = futures[future]; result = future.result()`
- `try/except` around `future.result()`, so one exception can't kill the batch
- `requests.RequestException` as the base class for every requests failure
- `time.monotonic()` around the call for latency

## Say this out loud (what the interviewer listens for)

- "This is I/O-bound, and threads release the GIL while waiting on sockets, so a thread pool gives real speedup.
  CPU-bound work would need `ProcessPoolExecutor`."
- "`max_workers` is a politeness limit. 500 simultaneous connections could exhaust file descriptors or look like an attack
  to the target. Pick it deliberately."
- "`as_completed` lets me process results as they arrive, for progress or early alerting. `pool.map` keeps order but
  waits on the slowest item before anything behind it comes out."
- "Total time ≈ slowest single check × (urls / workers), so the per-request timeout bounds the whole run."
- "At thousands of hosts I'd consider asyncio + aiohttp, but a thread pool is simpler to get right and to read in an incident."

## Traps

- Calling `future.result()` without try/except, so the first exception propagates and the other results are lost.
- `pool.submit(check_endpoint(url, timeout))`: calling the function instead of passing it. That runs everything sequentially.
- Forgetting the per-request `timeout`, so one blackholed host holds a worker forever.
- Duplicate URLs collapse into one dict key. Mention it, or dedupe up front on purpose.
