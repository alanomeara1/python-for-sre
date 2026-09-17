import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class ScriptedHandler(BaseHTTPRequestHandler):
    """Replies with the next (status, headers) from server.script; the last entry repeats."""

    def do_GET(self):
        script = self.server.script
        status, headers = script.pop(0) if len(script) > 1 else script[0]
        self.server.hits += 1
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHandler)
    srv.script, srv.hits = [(200, {})], 0
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}/inventory"
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def sleeps():
    return []


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/"


def test_backoff_exponential_and_capped(solution):
    assert solution.backoff_delays(0.5, 5, cap=4.0) == [0.5, 1.0, 2.0, 4.0, 4.0]
    assert solution.backoff_delays(1.0, 0, cap=10.0) == []


def test_backoff_jitter_uses_rng(solution):
    assert solution.backoff_delays(1.0, 3, cap=10.0, rng=lambda: 0.5) == [0.5, 1.0, 2.0]


def test_success_first_try_no_sleep(solution, server, sleeps):
    r = solution.fetch_with_retry(server.url, sleep=sleeps.append)
    assert r.status_code == 200
    assert server.hits == 1
    assert sleeps == []


def test_retries_5xx_then_succeeds_with_backoff(solution, server, sleeps):
    server.script = [(503, {}), (502, {}), (200, {})]
    r = solution.fetch_with_retry(server.url, attempts=3, base_delay=0.5, sleep=sleeps.append)
    assert r.status_code == 200
    assert server.hits == 3
    assert sleeps == [0.5, 1.0]


def test_429_honours_numeric_retry_after(solution, server, sleeps):
    server.script = [(429, {"Retry-After": "7"}), (200, {})]
    r = solution.fetch_with_retry(server.url, sleep=sleeps.append)
    assert r.status_code == 200
    assert sleeps == [7.0]


def test_does_not_retry_other_4xx(solution, server, sleeps):
    server.script = [(404, {})]
    r = solution.fetch_with_retry(server.url, sleep=sleeps.append)
    assert r.status_code == 404
    assert server.hits == 1
    assert sleeps == []


def test_gives_up_after_attempts_without_final_sleep(solution, server, sleeps):
    server.script = [(500, {})]
    with pytest.raises(solution.RetryError) as exc:
        solution.fetch_with_retry(server.url, attempts=4, base_delay=1.0, sleep=sleeps.append)
    assert server.hits == 4
    assert sleeps == [1.0, 2.0, 4.0]
    assert "4 attempts" in str(exc.value)
    assert "500" in str(exc.value)


def test_retries_connection_errors(solution, sleeps):
    with pytest.raises(solution.RetryError) as exc:
        solution.fetch_with_retry(closed_port_url(), attempts=3, base_delay=0.1, sleep=sleeps.append)
    assert sleeps == [0.1, 0.2]
    assert "ConnectionError" in str(exc.value)


def test_uses_injected_session_and_timeout(solution, sleeps):
    class FakeResponse:
        status_code = 204
        headers = {}

    class FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout=None):
            self.calls.append((url, timeout))
            return FakeResponse()

    session = FakeSession()
    r = solution.fetch_with_retry("http://svc/health", timeout=1.5, session=session, sleep=sleeps.append)
    assert r.status_code == 204
    assert session.calls == [("http://svc/health", 1.5)]
