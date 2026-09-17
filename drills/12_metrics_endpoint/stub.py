"""Stdlib-only Prometheus metrics, a timing context manager, and /metrics + /healthz.

Spec: drills/12_metrics_endpoint/README.md
"""

from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from typing import Callable


class Metrics:
    def __init__(self):
        raise NotImplementedError

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1) -> None:
        raise NotImplementedError

    def observe(self, name: str, seconds: float) -> None:
        raise NotImplementedError

    def render(self) -> str:
        raise NotImplementedError


@contextmanager
def timed(metrics: Metrics, name: str):
    raise NotImplementedError
    yield


def make_server(metrics: Metrics, checks: dict[str, Callable[[], bool]],
                host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    raise NotImplementedError
