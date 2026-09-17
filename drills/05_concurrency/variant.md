# 05 · Variant: concurrent TCP port checker

Same pool shape (`submit` → futures dict → `as_completed`), one layer lower: raw TCP instead of HTTP.
This is what you write when a firewall change goes out and you need to know *right now* which
host:port pairs are reachable.

## The task

> After the security group change, check that every (host, port) in this list still accepts TCP
> connections. Check them in parallel with a short timeout, and give me sorted open and closed lists.

## Contract

```python
def check_port(host: str, port: int, timeout: float) -> dict
    # {"open": bool, "latency": float, "error": str | None}
    # uses socket.create_connection((host, port), timeout=timeout), closing the socket afterwards
    # any OSError (refused, timed out, DNS failure) -> open False, error "<ExceptionClassName>: <message>"

def check_ports(targets: list[tuple[str, int]], timeout: float = 1.0, max_workers: int = 20) -> dict[tuple[str, int], dict]
    # {(host, port): check_port result}, concurrently

def summarize(results: dict[tuple[str, int], dict]) -> dict[str, list[tuple[str, int]]]
    # {"open": [...], "closed": [...]}, each sorted by (host, port)
```

Call it as `socket.create_connection(...)`. The tests patch it to prove the checks run concurrently.

## Say this out loud

- "`create_connection` does the DNS lookup and tries every address, IPv4 and IPv6. It beats hand-rolling `socket.socket()` + `connect()`."
- "Use `with` so the socket closes. Leaking a file descriptor per check across 10,000 checks will hit `ulimit -n`."
- "`OSError` covers refused, `TimeoutError` and `socket.gaierror`, because they all subclass it. I don't need three except clauses."
- "Refused is fast: something answered with a reset. A timeout is slow and usually means a firewall dropped the packets.
  Those are different problems, which is why I keep the error text."
- "Tuples as dict keys, and sorting by tuple, give deterministic output that's easy to diff before and after the change."
