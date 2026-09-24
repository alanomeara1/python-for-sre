"""Check TCP reachability of many host:port pairs concurrently.

Same pool pattern as the HTTP checker, one layer down the stack: this proves a TCP handshake
completed, not that the service behind the port is healthy. Reasoning in EXPLAINED.md.
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def check_port(host: str, port: int, timeout: float) -> dict:
    start = time.monotonic()
    try:
        # create_connection resolves DNS and tries each address; `with` closes the fd.
        # Sockets are file descriptors: leak them across thousands of targets and you hit ulimit.
        with socket.create_connection((host, port), timeout=timeout):
            return {"open": True, "latency": time.monotonic() - start, "error": None}
    except OSError as exc:              # refused, TimeoutError and gaierror all subclass OSError
        return {"open": False, "latency": time.monotonic() - start,
                "error": f"{type(exc).__name__}: {exc}"}


def check_ports(targets: list[tuple[str, int]], timeout: float = 1.0,
                max_workers: int = 20) -> dict[tuple[str, int], dict]:
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Tuple keys work because tuples are hashable; lists would not be.
        futures = {pool.submit(check_port, host, port, timeout): (host, port) for host, port in targets}
        for future in as_completed(futures):
            # No try here, because check_port catches OSError itself. Note the trade-off: a bug
            # INSIDE check_port would sink the batch, which the HTTP version guards against.
            results[futures[future]] = future.result()
    return results


def summarize(results: dict[tuple[str, int], dict]) -> dict[str, list[tuple[str, int]]]:
    # sorted() on (host, port) tuples compares element by element, so host-then-port ordering
    # is free and the output is deterministic.
    return {
        "open": sorted(target for target, r in results.items() if r["open"]),
        "closed": sorted(target for target, r in results.items() if not r["open"]),
    }


if __name__ == "__main__":
    import sys

    # rsplit(":", 1) splits from the right, so an IPv6 literal or a hostname with colons
    # still yields exactly one port.
    pairs = [(h, int(p)) for h, p in (arg.rsplit(":", 1) for arg in sys.argv[1:])]
    for state, targets in summarize(check_ports(pairs)).items():
        for host, port in targets:
            print(f"{state:<6} {host}:{port}")
