from datetime import datetime, timedelta


def t(hour, minute=0):
    return datetime(2026, 9, 1, hour, minute)


def test_merge_overlapping_and_touching(solution):
    outages = [(t(10), t(10, 30)), (t(10, 20), t(11)), (t(11), t(11, 15))]
    assert solution.merge_intervals(outages) == [(t(10), t(11, 15))]


def test_merge_unsorted_and_disjoint(solution):
    assert solution.merge_intervals([(8, 9), (1, 3), (2, 4), (6, 7)]) == [(1, 4), (6, 7), (8, 9)]


def test_merge_contained_interval_keeps_outer_end(solution):
    assert solution.merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]


def test_merge_empty_and_generator(solution):
    assert solution.merge_intervals([]) == []
    assert solution.merge_intervals(iter([(5, 6), (1, 2)])) == [(1, 2), (5, 6)]


def test_total_downtime_numbers_merges_before_summing(solution):
    assert solution.total_downtime([(10, 20), (15, 25)], 0, 100) == 15


def test_total_downtime_clips_to_window(solution):
    outages = [(-50, 10), (90, 200), (300, 400)]
    assert solution.total_downtime(outages, 0, 100) == 20


def test_total_downtime_datetimes_returns_timedelta(solution):
    outages = [(t(9, 50), t(10, 10)), (t(10, 5), t(10, 20))]
    assert solution.total_downtime(outages, t(10), t(11)) == timedelta(minutes=20)
    assert solution.total_downtime([], t(10), t(11)) == timedelta(0)


def test_availability(solution):
    start, end = datetime(2026, 9, 1), datetime(2026, 10, 1)       # 30 days
    outages = [(t(10), t(10) + timedelta(minutes=43, seconds=12))]    # 43m12s = 0.1% of 30 days
    assert abs(solution.availability(outages, start, end) - 0.999) < 1e-9
    assert solution.availability([], 0, 100) == 1.0


def test_concurrent_outages_two_of_three(solution):
    outages = {
        "api": [(0, 10)],
        "db": [(5, 15)],
        "cache": [(12, 20)],
    }
    assert solution.concurrent_outages(outages, 2) == [(5, 10), (12, 15)]
    assert solution.concurrent_outages(outages, 3) == []
    assert solution.concurrent_outages(outages, 1) == [(0, 20)]


def test_concurrent_outages_touching_is_not_concurrent(solution):
    outages = {"api": [(0, 10)], "db": [(10, 20)]}
    assert solution.concurrent_outages(outages, 2) == []


def test_concurrent_outages_service_overlapping_itself_counts_once(solution):
    outages = {"api": [(0, 10), (5, 15)], "db": [(100, 110)]}
    assert solution.concurrent_outages(outages, 2) == []


def test_concurrent_outages_contiguous_periods_are_merged(solution):
    outages = {"a": [(0, 10)], "b": [(0, 5)], "c": [(5, 10)]}
    assert solution.concurrent_outages(outages, 2) == [(0, 10)]


def test_concurrent_outages_datetimes_and_zero_length(solution):
    outages = {"api": [(t(10), t(11)), (t(10, 30), t(10, 30))], "db": [(t(10, 30), t(12))]}
    assert solution.concurrent_outages(outages, 2) == [(t(10, 30), t(11))]
