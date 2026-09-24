"""Stdlib-only Prometheus metrics, a timing context manager, and /metrics + /healthz.

Three pieces that barely know each other: a thread-safe store, a timer that feeds it,
and an HTTP shell that serves it. The hard part is that workers call inc() while the
server thread calls render(). Full reasoning in EXPLAINED.md.
"""

import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


def _escape(value: str) -> str:
    # Backslash FIRST. Escape quotes first and the backslashes you just inserted get
    # escaped again by the backslash rule -- the general rule for any encoder.
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self):
        # The server thread renders while worker threads increment: guard everything.
        self._lock = threading.Lock()
        # defaultdict(float): a missing series reads as 0.0, so += needs no setup.
        self._counters = defaultdict(float)      # (name, sorted label tuple) -> value
        # Separate dict because a summary renders as TWO samples (_sum and _count).
        # A list, not a tuple, because it is mutated in place.
        self._summaries = {}                     # name -> [sum, count]

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1) -> None:
        # A counter that can go down isn't a counter: rate(), increase() and every alert built
        # on them read a decrease as a reset. Reject it here rather than debug the graph later.
        if value < 0:
            raise ValueError("counters only go up")
        # labels=None, never labels={}: a mutable default is created ONCE at def time and
        # shared by every call for the life of the process.
        # sorted() so {"path":"/", "code":"200"} and {"code":"200", "path":"/"} are the SAME
        # series -- label order carries no meaning in Prometheus.
        key = (name, tuple(sorted((labels or {}).items())))   # dicts aren't hashable; tuples are
        # += is read-modify-write: load, add, store. Two threads can both load 7 and both
        # store 8, losing an increment. The GIL can be released between bytecodes, so it is
        # no protection. The 8-thread test demands exactly 40000.
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            # setdefault fetches or installs in one step, leaving no check-then-insert gap
            # for another thread to slip through.
            # Keeping only sum and count is what a Prometheus summary does: fixed memory per
            # series however many observations. The cost is no true percentiles later -- that
            # needs a histogram with buckets.
            totals = self._summaries.setdefault(name, [0.0, 0])
            totals[0] += seconds
            totals[1] += 1

    def render(self) -> str:
        with self._lock:                         # snapshot under the lock, format outside it
            # Formatting is slow string work; holding the lock through it would block every
            # worker in the process on every scrape. Copy fast, release, then take your time.
            # sorted() for deterministic, diffable output -- and it groups each metric family
            # together, which the "# TYPE once per family" logic below depends on.
            counters = sorted(self._counters.items())
            # list(t) COPIES the mutable [sum, count]; keeping the reference would leave the
            # "snapshot" pointing at live data that workers keep mutating while you format.
            summaries = sorted((name, list(t)) for name, t in self._summaries.items())

        lines = []
        last_name = None
        for (name, labels), value in counters:
            # One TYPE line per metric family, before its first sample -- not per sample.
            if name != last_name:
                lines.append(f"# TYPE {name} counter")
                last_name = name
            label_part = ""
            # No braces at all when unlabelled: `jobs_total 1.0`, not `jobs_total{} 1.0`.
            if labels:
                label_part = "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels) + "}"
            # !r is repr(): for a float, the shortest string that round-trips. float() first so
            # a counter renders as 2.0, the conventional form.
            lines.append(f"{name}{label_part} {float(value)!r}")
        for name, (total, count) in summaries:
            lines.append(f"# TYPE {name} summary")
            lines.append(f"{name}_sum {float(total)!r}")
            lines.append(f"{name}_count {count}")      # _count is an int by convention
        # join + one trailing newline: exactly one separator between lines, and the format
        # requires the document to end with a newline.
        return "\n".join(lines) + "\n"


@contextmanager
def timed(metrics: Metrics, name: str):
    # perf_counter, never time.time(): it is monotonic, so an NTP step, a resumed VM or a
    # manual clock change can't produce a NEGATIVE duration that poisons the sum.
    start = time.perf_counter()                  # monotonic: clock changes can't go negative
    try:
        yield
    # finally, so an exception inside the block still records. Without it you lose exactly the
    # slow failing calls you care about, and latency graphs LOOK BETTER during an incident.
    finally:                                     # record slow failures too, not just successes
        metrics.observe(name, time.perf_counter() - start)


def _passes(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    # Fail closed. A 500 from /healthz is indistinguishable from the endpoint itself being
    # broken, and it loses the body naming WHICH dependency failed -- the whole diagnostic
    # value. The load balancer treats 500 and 503 the same anyway.
    # `except Exception`, not bare `except:`, so Ctrl-C still works.
    except Exception:                            # a crashing check is a failed check, never a 500
        return False


def make_server(metrics: Metrics, checks: dict[str, Callable[[], bool]],
                host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    # Handler defined INSIDE the factory so it closes over metrics and checks: the server
    # instantiates a fresh handler per request, so there is nowhere to pass constructor args.
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                self._send(200, metrics.render(), "text/plain; version=0.0.4")
            elif self.path == "/healthz":
                # Checks run per request, not once at build time: a cached answer is not health.
                # sorted() so the failure list is deterministic.
                failed = sorted(name for name, check in checks.items() if not _passes(check))
                if failed:
                    self._send(503, json.dumps({"status": "fail", "failed": failed}), "application/json")
                else:
                    self._send(200, json.dumps({"status": "ok"}), "application/json")
            else:
                self._send(404, "not found\n", "text/plain")

        def _send(self, status: int, body: str, content_type: str):
            data = body.encode()                 # wfile is a BINARY stream; writing str raises
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            # Length of the ENCODED bytes, not of the str: they differ as soon as anything is
            # non-ASCII. Omit this and a keep-alive client waits for an EOF that never comes.
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()                   # the blank line; forget it and the client hangs
            self.wfile.write(data)

        # Prometheus scrapes every 15s: the default would write 5,760 junk lines a day per target.
        def log_message(self, format, *args):    # default writes every request to stderr
            pass

    # ThreadingHTTPServer, not HTTPServer: one thread per request, so a slow health check can't
    # block a scrape. That choice is exactly why Metrics needs its lock.
    # port=0 lets the OS pick a free port (read it back from server.server_address[1]), so tests
    # never collide. Returned UNSTARTED: the caller owns the lifecycle, which keeps it testable.
    return ThreadingHTTPServer((host, port), Handler)
