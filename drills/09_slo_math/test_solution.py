import pytest
from pytest import approx


def test_percentile_nearest_rank(solution):
    data = [35, 20, 50, 15, 40]              # unsorted on purpose
    assert solution.percentile(data, 30) == 20.0
    assert solution.percentile(data, 40) == 20.0
    assert solution.percentile(data, 50) == 35.0
    assert solution.percentile(data, 100) == 50.0
    assert solution.percentile(data, 0) == 15.0
    assert isinstance(solution.percentile(data, 50), float)


def test_percentile_no_float_rank_error(solution):
    data = list(range(1, 101))
    assert solution.percentile(data, 7) == 7.0          # p / 100 * n would give 8
    assert solution.percentile(data, 99) == 99.0
    assert solution.percentile(list(range(1, 1001)), 99.9) == 999.0


def test_percentile_accepts_generator(solution):
    assert solution.percentile((x for x in [3, 1, 2]), 50) == 2.0


def test_percentile_invalid_input(solution):
    with pytest.raises(ValueError):
        solution.percentile([], 50)
    with pytest.raises(ValueError):
        solution.percentile(iter([]), 50)
    with pytest.raises(ValueError):
        solution.percentile([1, 2, 3], 101)


def test_availability(solution):
    assert solution.availability(999, 1000) == approx(0.999)
    assert solution.availability(0, 0) == 1.0


def test_error_budget_remaining(solution):
    assert solution.error_budget_remaining(0.999, 1_000_000, 1_000_000) == approx(1.0)
    assert solution.error_budget_remaining(0.999, 999_500, 1_000_000) == approx(0.5)
    assert solution.error_budget_remaining(0.999, 999_000, 1_000_000) == approx(0.0, abs=1e-9)
    assert solution.error_budget_remaining(0.999, 998_000, 1_000_000) == approx(-1.0)
    assert solution.error_budget_remaining(0.99, 0, 0) == 1.0


def test_error_budget_rejects_impossible_slo(solution):
    with pytest.raises(ValueError):
        solution.error_budget_remaining(1.0, 10, 10)
    with pytest.raises(ValueError):
        solution.error_budget_remaining(99.9, 10, 10)     # percent, not fraction


def test_burn_rate(solution):
    assert solution.burn_rate(0.999, 0.001) == approx(1.0)
    assert solution.burn_rate(0.999, 0.0144) == approx(14.4)
    assert solution.burn_rate(0.99, 0.0) == 0.0


def test_should_page_needs_both_windows(solution):
    assert solution.should_page(0.999, short_window_error_rate=0.02, long_window_error_rate=0.015) is True
    # Long window burning, but the short window has recovered: don't page.
    assert solution.should_page(0.999, short_window_error_rate=0.001, long_window_error_rate=0.02) is False
    # Short spike, long window fine: don't page.
    assert solution.should_page(0.999, short_window_error_rate=0.5, long_window_error_rate=0.01) is False


def test_should_page_custom_threshold(solution):
    assert solution.should_page(0.999, 0.007, 0.007, threshold=6) is True
    assert solution.should_page(0.999, 0.007, 0.007) is False
