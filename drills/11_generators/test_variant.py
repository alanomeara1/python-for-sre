import itertools

import pytest


def test_top_k_basic(variant):
    events = [{"path": "/api"}, {"path": "/login"}, {"path": "/api"}, {"user": "no path"}, {"path": "/x"}]
    assert variant.top_k(events, 1, "path") == [("/api", 2)]
    assert variant.top_k(events, 10, "path") == [("/api", 2), ("/login", 1), ("/x", 1)]


def test_top_k_ties_first_seen_first(variant):
    events = ({"ip": ip} for ip in ["c", "b", "a", "a", "b", "c", "d"])
    assert variant.top_k(events, 3, "ip") == [("c", 2), ("b", 2), ("a", 2)]


def test_top_k_empty(variant):
    assert variant.top_k([], 5, "path") == []


def test_dedupe_consecutive(variant):
    lines = ["boom", "boom", "ok", "boom", "boom", "boom"]
    assert list(variant.dedupe_consecutive(lines)) == [("boom", 2), ("ok", 1), ("boom", 3)]
    assert list(variant.dedupe_consecutive([])) == []


def test_dedupe_consecutive_is_lazy(variant):
    endless = itertools.chain(["a", "a", "b"], itertools.repeat("c"))
    gen = variant.dedupe_consecutive(endless)
    assert next(gen) == ("a", 2)
    assert next(gen) == ("b", 1)


def test_window_counts(variant):
    assert list(variant.window_counts([0, 5, 59, 60, 61, 185], 60)) == [(0, 3), (60, 2), (180, 1)]
    assert list(variant.window_counts([], 60)) == []


def test_window_counts_float_timestamps_give_int_buckets(variant):
    out = list(variant.window_counts([1726567200.25, 1726567209.9, 1726567210.0], 10))
    assert out == [(1726567200, 2), (1726567210, 1)]
    assert all(isinstance(bucket, int) for bucket, _ in out)


def test_window_counts_yields_before_input_ends(variant):
    def stream():
        yield from [0, 1, 2, 10]
        raise AssertionError("consumed past the first completed bucket")

    assert next(variant.window_counts(stream(), 10)) == (0, 3)


def test_window_counts_rejects_out_of_order(variant):
    with pytest.raises(ValueError):
        list(variant.window_counts([100, 200, 50], 60))
