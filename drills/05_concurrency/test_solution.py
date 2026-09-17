import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

SLOW = 0.3


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(SLOW)
        status = 500 if self.path.startswith("/error") else 200
        self.send_response(status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                                   # client timed out and hung up: expected in one test


@pytest.fixture(scope="module")
def base_url():
    srv = QuietServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/health"


def test_check_endpoint_ok(solution, base_url):
    r = solution.check_endpoint(f"{base_url}/health", timeout=2)
    assert r["ok"] is True
    assert r["status"] == 200
    assert r["error"] is None
    assert isinstance(r["latency"], float) and r["latency"] >= 0


def test_check_endpoint_http_error(solution, base_url):
    r = solution.check_endpoint(f"{base_url}/error", timeout=2)
    assert r["ok"] is False
    assert r["status"] == 500
    assert r["error"] == "HTTP 500"


def test_check_endpoint_connection_refused(solution):
    r = solution.check_endpoint(closed_port_url(), timeout=2)
    assert r["ok"] is False
    assert r["status"] is None
    assert r["error"].startswith("ConnectionError")


def test_check_endpoint_timeout(solution, base_url):
    r = solution.check_endpoint(f"{base_url}/slow", timeout=0.05)
    assert r["ok"] is False
    assert r["status"] is None
    assert "timeout" in r["error"].lower()


def test_check_endpoints_runs_concurrently(solution, base_url):
    urls = [f"{base_url}/slow?n={i}" for i in range(8)]
    start = time.monotonic()
    results = solution.check_endpoints(urls, max_workers=8, timeout=2)
    elapsed = time.monotonic() - start
    assert set(results) == set(urls)
    assert all(r["ok"] for r in results.values())
    assert elapsed < SLOW * 8 / 2, f"took {elapsed:.2f}s: looks sequential"


def test_check_endpoints_respects_max_workers(solution, base_url):
    urls = [f"{base_url}/slow?n={i}" for i in range(4)]
    start = time.monotonic()
    solution.check_endpoints(urls, max_workers=1, timeout=2)
    assert time.monotonic() - start >= SLOW * 4 * 0.9


def test_check_endpoints_one_failure_does_not_break_batch(solution, base_url):
    bad, err, good = closed_port_url(), f"{base_url}/error", f"{base_url}/health"
    results = solution.check_endpoints([bad, err, good], timeout=2)
    assert results[good]["ok"] is True
    assert results[err]["status"] == 500
    assert results[bad]["status"] is None and results[bad]["ok"] is False


def test_check_endpoints_empty(solution):
    assert solution.check_endpoints([]) == {}
