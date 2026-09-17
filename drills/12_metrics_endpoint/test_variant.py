import math

import pytest

SCRAPE = """
# HELP http_requests_total Total requests.
# TYPE http_requests_total counter
http_requests_total{code="200",path="/"} 1027
http_requests_total{path="/api",code="500"} 3

process_start_time_seconds 1.7265672e+09
"""


def key(name, **labels):
    return (name, frozenset(labels.items()))


def test_parse_basic(variant):
    assert variant.parse_exposition(SCRAPE) == {
        key("http_requests_total", code="200", path="/"): 1027.0,
        key("http_requests_total", code="500", path="/api"): 3.0,
        key("process_start_time_seconds"): 1726567200.0,
    }


def test_parse_label_order_does_not_matter(variant):
    a = variant.parse_exposition('m{a="1",b="2"} 5')
    b = variant.parse_exposition('m{b="2",a="1"} 5')
    assert a == b


def test_parse_commas_spaces_and_escaped_quotes_in_values(variant):
    out = variant.parse_exposition('errors_total{msg="bad, \\"very\\" bad",path="/a b"} 2')
    assert out == {key("errors_total", msg='bad, "very" bad', path="/a b"): 2.0}


def test_parse_special_values_and_timestamp(variant):
    out = variant.parse_exposition("up 1 1726567200000\ntemp NaN\nlimit +Inf\n")
    assert out[key("up")] == 1.0
    assert math.isnan(out[key("temp")])
    assert out[key("limit")] == math.inf


def test_parse_empty(variant):
    assert variant.parse_exposition("# only comments\n\n") == {}


def test_counter_rate(variant):
    prev = {key("req", code="200"): 1000.0, key("req", code="500"): 10.0}
    curr = {key("req", code="200"): 1600.0, key("req", code="500"): 10.0}
    assert variant.counter_rate(prev, curr, 60) == {key("req", code="200"): 10.0, key("req", code="500"): 0.0}


def test_counter_rate_handles_reset(variant):
    prev = {key("req"): 5000.0}
    curr = {key("req"): 120.0}
    assert variant.counter_rate(prev, curr, 30) == {key("req"): 4.0}


def test_counter_rate_skips_series_without_baseline(variant):
    prev = {key("old"): 1.0}
    curr = {key("new"): 50.0, key("old"): 3.0}
    assert variant.counter_rate(prev, curr, 2) == {key("old"): 1.0}


def test_counter_rate_rejects_bad_interval(variant):
    with pytest.raises(ValueError):
        variant.counter_rate({}, {}, 0)
