"""Check many HTTP endpoints concurrently with a thread pool.

One checker, one pool, one dict. All the error handling lives in check_endpoint, so the
concurrency layer only schedules and collects. Reasoning in EXPLAINED.md.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def check_endpoint(url: str, timeout: float) -> dict:
    start = time.monotonic()                          # monotonic: latency can never come out negative
    try:
        # timeout is what stops one blackholed host holding a worker thread forever.
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:           # base class: connection, timeout, bad URL...
        # Return, never raise: that contract is what keeps check_endpoints simple.
        # status is None because there was no HTTP response at all; 0 would be a lie.
        return {"ok": False, "status": None, "latency": time.monotonic() - start,
                "error": f"{type(exc).__name__}: {exc}"}

    ok = response.status_code < 400                    # 2xx and 3xx are both working servers
    # Same four keys on every path, so callers never write defensive .get() lookups.
    return {"ok": ok, "status": response.status_code, "latency": time.monotonic() - start,
            "error": None if ok else f"HTTP {response.status_code}"}


def check_endpoints(urls: list[str], max_workers: int = 10, timeout: float = 2.0) -> dict[str, dict]:
    results = {}
    # Threads suit I/O-bound work: each one releases the GIL while it waits on the network.
    # (CPU-bound work would need ProcessPoolExecutor.) `with` waits for every task and tears
    # the threads down; max_workers is a politeness limit on file descriptors and on the target.
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Map each future back to its URL, because as_completed yields futures in finish order.
        # submit(fn, arg) passes the function; submit(fn(arg)) would call it here, sequentially.
        futures = {pool.submit(check_endpoint, url, timeout): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()         # re-raises anything the task raised
            except Exception as exc:
                # check_endpoint shouldn't raise, but a bug in one check must not sink the batch.
                # latency 0.0: the failure was in our code, so there's nothing meaningful to report.
                results[url] = {"ok": False, "status": None, "latency": 0.0,
                                "error": f"{type(exc).__name__}: {exc}"}
    return results


if __name__ == "__main__":
    import sys

    for url, r in sorted(check_endpoints(sys.argv[1:]).items()):
        print(f"{'UP  ' if r['ok'] else 'DOWN'} {r['latency']:.3f}s {url} {r['error'] or ''}")
