"""Parse Prometheus text exposition and compute per-second counter rates."""

import re

SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?:\{(?P<labels>.*)\})?"          # greedy is fine: the value never contains "}"
    r"\s+(?P<value>\S+)"
    r"(?:\s+\d+)?\s*$"                  # optional timestamp, ignored
)
# A label value is a quoted string that may contain escaped chars, so commas inside it are safe.
LABEL_RE = re.compile(r'(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)="(?P<value>(?:[^"\\]|\\.)*)"')


def _unescape(value: str) -> str:
    # One pass over "\x" pairs. Chained .replace() calls get "\\n" (escaped backslash, then n) wrong.
    return re.sub(r"\\(.)", lambda m: "\n" if m[1] == "n" else m[1], value)


def parse_exposition(text: str) -> dict[tuple[str, frozenset], float]:
    samples = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = SAMPLE_RE.match(line)
        if not match:
            continue
        labels = frozenset(
            (m["key"], _unescape(m["value"])) for m in LABEL_RE.finditer(match["labels"] or "")
        )
        # frozenset: hashable, and label order in the text doesn't create a different series
        samples[(match["name"], labels)] = float(match["value"])
    return samples


def counter_rate(prev: dict, curr: dict, seconds: float) -> dict[tuple[str, frozenset], float]:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    rates = {}
    for series, value in curr.items():
        if series not in prev:
            continue                    # no baseline yet
        increase = value - prev[series]
        if increase < 0:
            increase = value            # counter reset: it restarted from 0 and climbed to value
        rates[series] = increase / seconds
    return rates
