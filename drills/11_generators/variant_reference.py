"""Single-pass, bounded-memory aggregation over an event stream."""

import heapq
from collections import Counter
from itertools import groupby
from typing import Iterable, Iterator


def top_k(events: Iterable[dict], k: int, key: str) -> list[tuple[object, int]]:
    counts = Counter()
    for event in events:
        if key in event:
            counts[event[key]] += 1
    # Counter keeps first-seen order, and nlargest is stable, so ties come out deterministically.
    return heapq.nlargest(k, counts.items(), key=lambda item: item[1])


def dedupe_consecutive(lines: Iterable[str]) -> Iterator[tuple[str, int]]:
    # groupby groups ADJACENT equal items, which is exactly syslog's "repeated N times".
    for line, run in groupby(lines):
        yield line, sum(1 for _ in run)


def window_counts(timestamps: Iterable[float], bucket_seconds: int) -> Iterator[tuple[int, int]]:
    current_bucket = None
    count = 0
    for ts in timestamps:
        bucket = int(ts // bucket_seconds) * bucket_seconds
        if current_bucket is not None and bucket < current_bucket:
            raise ValueError(f"out-of-order timestamp {ts} (current bucket {current_bucket})")
        if bucket != current_bucket:
            if current_bucket is not None:
                yield current_bucket, count     # bucket is complete: emit now, hold nothing
            current_bucket, count = bucket, 0
        count += 1
    if current_bucket is not None:
        yield current_bucket, count
