"""Stdlib-only Prometheus metrics, a timing context manager, and /metrics + /healthz."""

import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self):
        # The server thread renders while worker threads increment: guard everything.
        self._lock = threading.Lock()
        self._counters = defaultdict(float)      # (name, sorted label tuple) -> value
        self._summaries = {}                     # name -> [sum, count]

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1) -> None:
        if value < 0:
            raise ValueError("counters only go up")
        key = (name, tuple(sorted((labels or {}).items())))   # dicts aren't hashable; tuples are
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            totals = self._summaries.setdefault(name, [0.0, 0])
            totals[0] += seconds
            totals[1] += 1

    def render(self) -> str:
        with self._lock:                         # snapshot under the lock, format outside it
            counters = sorted(self._counters.items())
            summaries = sorted((name, list(t)) for name, t in self._summaries.items())

        lines = []
        last_name = None
        for (name, labels), value in counters:
            if name != last_name:
                lines.append(f"# TYPE {name} counter")
                last_name = name
            label_part = ""
            if labels:
                label_part = "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels) + "}"
            lines.append(f"{name}{label_part} {float(value)!r}")
        for name, (total, count) in summaries:
            lines.append(f"# TYPE {name} summary")
            lines.append(f"{name}_sum {float(total)!r}")
            lines.append(f"{name}_count {count}")
        return "\n".join(lines) + "\n"


@contextmanager
def timed(metrics: Metrics, name: str):
    start = time.perf_counter()                  # monotonic: clock changes can't go negative
    try:
        yield
    finally:                                     # record slow failures too, not just successes
        metrics.observe(name, time.perf_counter() - start)


def _passes(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:                            # a crashing check is a failed check, never a 500
        return False


def make_server(metrics: Metrics, checks: dict[str, Callable[[], bool]],
                host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                self._send(200, metrics.render(), "text/plain; version=0.0.4")
            elif self.path == "/healthz":
                failed = sorted(name for name, check in checks.items() if not _passes(check))
                if failed:
                    self._send(503, json.dumps({"status": "fail", "failed": failed}), "application/json")
                else:
                    self._send(200, json.dumps({"status": "ok"}), "application/json")
            else:
                self._send(404, "not found\n", "text/plain")

        def _send(self, status: int, body: str, content_type: str):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):    # default writes every request to stderr
            pass

    return ThreadingHTTPServer((host, port), Handler)
