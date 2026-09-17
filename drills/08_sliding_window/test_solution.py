import time

import pytest


def test_error_rate_basic(solution):
    m = solution.ErrorRateMonitor(window_seconds=60, threshold=0.5)
    assert m.error_rate(now=0) == 0.0
    m.record(1, ok=True)
    m.record(2, ok=False)
    m.record(3, ok=False)
    m.record(4, ok=True)
    assert m.error_rate(now=10) == pytest.approx(0.5)


def test_events_expire_at_window_boundary(solution):
    m = solution.ErrorRateMonitor(window_seconds=60, threshold=0.5)
    m.record(0, ok=False)
    m.record(30, ok=True)
    assert m.error_rate(now=59.9) == pytest.approx(0.5)
    assert m.error_rate(now=60) == 0.0          # t=0 expires exactly at 0 + 60
    assert m.error_rate(now=90) == 0.0          # t=30 expired too, window empty


def test_error_count_decrements_on_eviction(solution):
    m = solution.ErrorRateMonitor(window_seconds=10, threshold=0.5)
    for t in range(5):
        m.record(t, ok=False)
    for t in range(20, 25):
        m.record(t, ok=True)
    assert m.error_rate(now=25) == 0.0
    m.record(26, ok=False)
    assert m.error_rate(now=26) == pytest.approx(1 / 6)


def test_should_alert_respects_threshold_and_min_requests(solution):
    m = solution.ErrorRateMonitor(window_seconds=60, threshold=0.1, min_requests=5)
    m.record(0, ok=False)
    assert m.should_alert(now=1) is False       # 100% errors, but only 1 request
    for t in range(1, 10):
        m.record(t, ok=True)
    assert m.should_alert(now=10) is True       # 1/10 = 0.1 >= 0.1
    m.record(11, ok=True)
    assert m.should_alert(now=11) is False      # 1/11 < 0.1
    assert m.should_alert(now=100) is False     # everything expired


def test_monitor_is_fast_at_volume(solution):
    m = solution.ErrorRateMonitor(window_seconds=10, threshold=0.5)
    start = time.perf_counter()
    for i in range(100_000):
        t = i / 100
        m.record(t, ok=i % 3 != 0)
        m.error_rate(now=t)                      # O(window) per call would take far too long
    assert time.perf_counter() - start < 2.0
    assert m.error_rate(now=999.99) == pytest.approx(1 / 3, abs=0.01)


def test_rate_limiter_limit_and_window(solution):
    rl = solution.SlidingWindowRateLimiter(limit=3, window_seconds=10)
    assert [rl.allow("a", now=t) for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert rl.allow("a", now=9.9) is False
    assert rl.allow("a", now=10) is True        # t=0 expired exactly at 10
    assert rl.allow("a", now=10.5) is False


def test_rate_limiter_clients_are_independent(solution):
    rl = solution.SlidingWindowRateLimiter(limit=2, window_seconds=60)
    assert rl.allow("a", 0) and rl.allow("a", 1)
    assert rl.allow("a", 2) is False
    assert rl.allow("b", 2) is True


def test_rejected_requests_do_not_count(solution):
    rl = solution.SlidingWindowRateLimiter(limit=2, window_seconds=10)
    assert rl.allow("a", 0) and rl.allow("a", 5)
    for t in range(6, 10):
        assert rl.allow("a", t) is False         # hammering while limited
    assert rl.allow("a", 10) is True             # only t=0 and t=5 were ever recorded
