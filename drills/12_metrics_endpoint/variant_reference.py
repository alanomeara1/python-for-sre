"""Parse Prometheus text exposition and compute per-second counter rates.

The other side of the main drill. The two things that make it non-trivial: label
values are quoted strings (so you cannot split on commas), and counters reset when
a process restarts. Full reasoning in EXPLAINED.md.
"""

import re

SAMPLE_RE = re.compile(
    # Metric names may contain colons (recording rules) but never start with a digit.
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?:\{(?P<labels>.*)\})?"          # greedy is fine: the value never contains "}"
    r"\s+(?P<value>\S+)"
    r"(?:\s+\d+)?\s*$"                  # optional timestamp, ignored
)
# A label value is a quoted string that may contain escaped chars, so commas inside it are safe.
# (?:[^"\\]|\\.)* reads as "any char that is neither quote nor backslash, or an escaped pair".
# Splitting the label block on "," instead would break on path="/a,b", which is legal.
LABEL_RE = re.compile(r'(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)="(?P<value>(?:[^"\\]|\\.)*)"')


def _unescape(value: str) -> str:
    # One pass over "\x" pairs. Chained .replace() calls get "\\n" (escaped backslash, then n) wrong.
    # Walking each escape pair exactly once is the only correct way to reverse an escaping scheme.
    return re.sub(r"\\(.)", lambda m: "\n" if m[1] == "n" else m[1], value)


def parse_exposition(text: str) -> dict[tuple[str, frozenset], float]:
    samples = {}
    for line in text.splitlines():
        line = line.strip()
        # "#" covers both # HELP and # TYPE, which carry no sample data.
        if not line or line.startswith("#"):
            continue
        match = SAMPLE_RE.match(line)
        if not match:
            continue                    # skip what you don't understand rather than crash a scrape
        labels = frozenset(
            # No labels at all -> finditer over "" -> an empty frozenset, no special case needed.
            (m["key"], _unescape(m["value"])) for m in LABEL_RE.finditer(match["labels"] or "")
        )
        # frozenset: hashable, and label order in the text doesn't create a different series
        # (the main drill sorts a tuple for the same reason; a frozenset is order-free by
        # construction, which suits reading whatever order an exporter chose).
        # float() handles "NaN", "+Inf" and "1.7e+09" without help.
        samples[(match["name"], labels)] = float(match["value"])
    return samples


def counter_rate(prev: dict, curr: dict, seconds: float) -> dict[tuple[str, frozenset], float]:
    # Zero or negative would divide by zero or invert every rate.
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    rates = {}
    for series, value in curr.items():
        if series not in prev:
            continue                    # no baseline yet
        increase = value - prev[series]
        # The real content of this function, and exactly what PromQL's rate() does: a counter
        # only falls when the process restarted and began again at 0, so the increase is the
        # current value. Without this, every pod restart emits a huge negative rate and breaks
        # every alert on that series.
        if increase < 0:
            increase = value            # counter reset: it restarted from 0 and climbed to value
        rates[series] = increase / seconds
    return rates
