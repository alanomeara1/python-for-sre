from datetime import datetime, timezone

LOG = """\
10.0.0.1 - - [17/Sep/2026:10:15:32 +0000] "GET /api/users HTTP/1.1" 200 512 0.023
10.0.0.2 - - [17/Sep/2026:10:15:33 +0000] "POST /api/login HTTP/1.1" 503 - 1.204
10.0.0.1 - - [17/Sep/2026:10:15:34 +0000] "GET /healthz HTTP/1.1" 200 2 0.001
this line is garbage
10.0.0.3 - - [17/Sep/2026:10:15:35 +0000] "GET /api/orders HTTP/1.1" 404 128 0.010

10.0.0.1 - - [17/Sep/2026:10:15:36 +0000] "GET /api/users HTTP/1.1" 500 64 0.502
10.0.0.2 - - [17/Sep/2026:10:15:37 +0000] "GET /api/users HTTP/1.1" 200 512 0.030
"""


def test_parse_line_types(solution):
    r = solution.parse_line(LOG.splitlines()[0])
    assert r["ip"] == "10.0.0.1"
    assert r["time"] == datetime(2026, 9, 17, 10, 15, 32, tzinfo=timezone.utc)
    assert r["method"] == "GET"
    assert r["path"] == "/api/users"
    assert r["status"] == 200 and isinstance(r["status"], int)
    assert r["bytes"] == 512 and isinstance(r["bytes"], int)
    assert r["duration"] == 0.023 and isinstance(r["duration"], float)


def test_parse_line_dash_bytes(solution):
    r = solution.parse_line(LOG.splitlines()[1])
    assert r["bytes"] == 0
    assert r["status"] == 503


def test_parse_line_malformed_returns_none(solution):
    assert solution.parse_line("this line is garbage") is None


def test_summarize_counts(solution):
    s = solution.summarize(LOG.splitlines())
    assert s["total"] == 6
    assert s["malformed"] == 1
    assert s["status_counts"] == {200: 3, 503: 1, 404: 1, 500: 1}


def test_summarize_top_ips(solution):
    s = solution.summarize(LOG.splitlines(), top_n=2)
    assert s["top_ips"] == [("10.0.0.1", 3), ("10.0.0.2", 2)]


def test_summarize_error_rate_is_5xx_only(solution):
    s = solution.summarize(LOG.splitlines())
    assert abs(s["error_rate"] - 2 / 6) < 1e-9


def test_summarize_empty_input_no_zero_division(solution):
    s = solution.summarize([])
    assert s["total"] == 0
    assert s["error_rate"] == 0.0
    assert s["top_ips"] == []


def test_summarize_accepts_generator(solution):
    s = solution.summarize(line for line in LOG.splitlines())
    assert s["total"] == 6


def test_summarize_file(solution, tmp_path):
    log = tmp_path / "access.log"
    log.write_text(LOG)
    s = solution.summarize_file(log, top_n=1)
    assert s["total"] == 6
    assert s["top_ips"] == [("10.0.0.1", 3)]
