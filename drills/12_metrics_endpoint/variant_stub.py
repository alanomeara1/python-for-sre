"""Parse Prometheus text exposition and compute per-second counter rates.

Spec: drills/12_metrics_endpoint/variant.md
"""


def parse_exposition(text: str) -> dict[tuple[str, frozenset], float]:
    raise NotImplementedError


def counter_rate(prev: dict, curr: dict, seconds: float) -> dict[tuple[str, frozenset], float]:
    raise NotImplementedError
