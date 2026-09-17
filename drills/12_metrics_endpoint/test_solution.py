import json
import threading
import time
import urllib.error
import urllib.request

import pytest

EXPECTED = """\
# TYPE http_requests_total counter
http_requests_total{code="200",path="/"} 2.0
http_requests_total{code="500",path="/api"} 1.0
# TYPE jobs_total counter
jobs_total 1.0
# TYPE request_seconds summary
request_seconds_sum 0.75
request_seconds_count 2
"""


def get(url):
    """(status, headers, body) without raising on 4xx/5xx."""
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


@pytest.fixture
def serve(solution):
    servers = []

    def _serve(metrics, checks):
        server = solution.make_server(metrics, checks)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        servers.append(server)
        host, port = server.server_address[:2]
        return f"http://{host}:{port}"

    yield _serve
    for server in servers:
        server.shutdown()
        server.server_close()


def test_render_exact_format(solution):
    m = solution.Metrics()
    m.observe("request_seconds", 0.5)
    m.inc("http_requests_total", {"path": "/", "code": "200"})
    m.inc("jobs_total")
    m.inc("http_requests_total", {"code": "500", "path": "/api"})
    m.inc("http_requests_total", {"code": "200", "path": "/"})
    m.observe("request_seconds", 0.25)
    assert m.render() == EXPECTED


def test_inc_value_and_rejects_negative(solution):
    m = solution.Metrics()
    m.inc("bytes_total", value=1024)
    m.inc("bytes_total", value=0.5)
    assert "bytes_total 1024.5\n" in m.render()
    with pytest.raises(ValueError):
        m.inc("bytes_total", value=-1)


def test_label_values_are_escaped(solution):
    m = solution.Metrics()
    m.inc("errors_total", {"msg": 'say "hi"\\now\nplease'})
    assert 'errors_total{msg="say \\"hi\\"\\\\now\\nplease"} 1.0' in m.render()


def test_inc_is_thread_safe(solution):
    m = solution.Metrics()

    def work():
        for _ in range(5000):
            m.inc("hits_total", {"worker": "all"})

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert 'hits_total{worker="all"} 40000.0' in m.render()


def test_timed_observes_duration(solution):
    m = solution.Metrics()
    with solution.timed(m, "job_seconds"):
        time.sleep(0.02)
    out = m.render()
    assert "job_seconds_count 1\n" in out
    total = float(out.split("job_seconds_sum ")[1].split()[0])
    assert 0.02 <= total < 1


def test_timed_records_even_when_block_raises(solution):
    m = solution.Metrics()
    with pytest.raises(KeyError):
        with solution.timed(m, "job_seconds"):
            raise KeyError("boom")
    assert "job_seconds_count 1\n" in m.render()


def test_metrics_endpoint(solution, serve):
    m = solution.Metrics()
    m.inc("jobs_total")
    base = serve(m, {})
    status, headers, body = get(base + "/metrics")
    assert status == 200
    assert headers["Content-Type"] == "text/plain; version=0.0.4"
    assert body == "# TYPE jobs_total counter\njobs_total 1.0\n"


def test_healthz_ok(solution, serve):
    base = serve(solution.Metrics(), {"db": lambda: True, "disk": lambda: 1})
    status, headers, body = get(base + "/healthz")
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"status": "ok"}


def test_healthz_failing_and_raising_checks(solution, serve):
    def explode():
        raise ConnectionError("db unreachable")

    checks = {"disk": lambda: True, "queue": lambda: False, "db": explode}
    base = serve(solution.Metrics(), checks)
    status, _, body = get(base + "/healthz")
    assert status == 503
    assert json.loads(body) == {"status": "fail", "failed": ["db", "queue"]}


def test_unknown_path_is_404(solution, serve):
    base = serve(solution.Metrics(), {})
    status, _, _ = get(base + "/nope")
    assert status == 404
