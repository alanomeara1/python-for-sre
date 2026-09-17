"""Check many HTTP endpoints concurrently with a thread pool."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def check_endpoint(url: str, timeout: float) -> dict:
    start = time.monotonic()
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:           # base class: connection, timeout, bad URL...
        return {"ok": False, "status": None, "latency": time.monotonic() - start,
                "error": f"{type(exc).__name__}: {exc}"}

    ok = response.status_code < 400
    return {"ok": ok, "status": response.status_code, "latency": time.monotonic() - start,
            "error": None if ok else f"HTTP {response.status_code}"}


def check_endpoints(urls: list[str], max_workers: int = 10, timeout: float = 2.0) -> dict[str, dict]:
    results = {}
    # Threads suit I/O-bound work: each one releases the GIL while it waits on the network.
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Map each future back to its URL, because as_completed yields futures in finish order.
        futures = {pool.submit(check_endpoint, url, timeout): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as exc:
                # check_endpoint shouldn't raise, but a bug in one check must not sink the batch.
                results[url] = {"ok": False, "status": None, "latency": 0.0,
                                "error": f"{type(exc).__name__}: {exc}"}
    return results


if __name__ == "__main__":
    import sys

    for url, r in sorted(check_endpoints(sys.argv[1:]).items()):
        print(f"{'UP  ' if r['ok'] else 'DOWN'} {r['latency']:.3f}s {url} {r['error'] or ''}")
