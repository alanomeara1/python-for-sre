import socket
import time

import pytest


@pytest.fixture
def listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    yield s.getsockname()[1]
    s.close()


@pytest.fixture
def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_check_port_open(variant, listener):
    r = variant.check_port("127.0.0.1", listener, timeout=1)
    assert r["open"] is True
    assert r["error"] is None
    assert isinstance(r["latency"], float)


def test_check_port_closed(variant, closed_port):
    r = variant.check_port("127.0.0.1", closed_port, timeout=1)
    assert r["open"] is False
    assert r["error"].startswith("ConnectionRefusedError")


def test_check_port_closes_the_socket(variant, monkeypatch):
    closed = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            closed.append(True)

    monkeypatch.setattr(variant.socket, "create_connection", lambda addr, timeout=None: FakeConn())
    assert variant.check_port("db.internal", 5432, timeout=1)["open"] is True
    assert closed == [True]


def test_check_ports_mixed(variant, listener, closed_port):
    targets = [("127.0.0.1", listener), ("127.0.0.1", closed_port)]
    results = variant.check_ports(targets, timeout=1)
    assert set(results) == set(targets)
    assert results[("127.0.0.1", listener)]["open"] is True
    assert results[("127.0.0.1", closed_port)]["open"] is False


def test_check_ports_runs_concurrently(variant, monkeypatch):
    class SlowConn:
        def __init__(self):
            time.sleep(0.2)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    monkeypatch.setattr(variant.socket, "create_connection", lambda addr, timeout=None: SlowConn())
    targets = [("10.0.0.1", p) for p in range(10)]
    start = time.monotonic()
    results = variant.check_ports(targets, timeout=1, max_workers=10)
    assert len(results) == 10
    assert time.monotonic() - start < 1.0


def test_summarize_sorted_by_host_then_port(variant):
    results = {
        ("10.0.0.2", 80): {"open": True, "latency": 0.01, "error": None},
        ("10.0.0.1", 443): {"open": True, "latency": 0.01, "error": None},
        ("10.0.0.1", 22): {"open": True, "latency": 0.01, "error": None},
        ("10.0.0.1", 9): {"open": False, "latency": 1.0, "error": "TimeoutError: timed out"},
    }
    assert variant.summarize(results) == {
        "open": [("10.0.0.1", 22), ("10.0.0.1", 443), ("10.0.0.2", 80)],
        "closed": [("10.0.0.1", 9)],
    }
