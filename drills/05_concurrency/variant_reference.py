"""Check TCP reachability of many host:port pairs concurrently."""

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def check_port(host: str, port: int, timeout: float) -> dict:
    start = time.monotonic()
    try:
        # create_connection resolves DNS and tries each address; `with` closes the fd.
        with socket.create_connection((host, port), timeout=timeout):
            return {"open": True, "latency": time.monotonic() - start, "error": None}
    except OSError as exc:              # refused, TimeoutError and gaierror all subclass OSError
        return {"open": False, "latency": time.monotonic() - start,
                "error": f"{type(exc).__name__}: {exc}"}


def check_ports(targets: list[tuple[str, int]], timeout: float = 1.0,
                max_workers: int = 20) -> dict[tuple[str, int], dict]:
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(check_port, host, port, timeout): (host, port) for host, port in targets}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results


def summarize(results: dict[tuple[str, int], dict]) -> dict[str, list[tuple[str, int]]]:
    return {
        "open": sorted(target for target, r in results.items() if r["open"]),
        "closed": sorted(target for target, r in results.items() if not r["open"]),
    }


if __name__ == "__main__":
    import sys

    pairs = [(h, int(p)) for h, p in (arg.rsplit(":", 1) for arg in sys.argv[1:])]
    for state, targets in summarize(check_ports(pairs)).items():
        for host, port in targets:
            print(f"{state:<6} {host}:{port}")
