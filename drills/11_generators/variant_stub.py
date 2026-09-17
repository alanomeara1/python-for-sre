"""Single-pass, bounded-memory aggregation over an event stream.

Spec: drills/11_generators/variant.md
"""

from typing import Iterable, Iterator


def top_k(events: Iterable[dict], k: int, key: str) -> list[tuple[object, int]]:
    raise NotImplementedError


def dedupe_consecutive(lines: Iterable[str]) -> Iterator[tuple[str, int]]:
    raise NotImplementedError


def window_counts(timestamps: Iterable[float], bucket_seconds: int) -> Iterator[tuple[int, int]]:
    raise NotImplementedError
