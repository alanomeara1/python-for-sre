"""Streaming log toolkit: lazy read, grep, JSON lines, batching, tail -f.

Spec: drills/11_generators/README.md
"""

import time
from pathlib import Path
from typing import Callable, Iterable, Iterator


def read_lines(path: str | Path) -> Iterator[str]:
    raise NotImplementedError


def grep(pattern: str, lines: Iterable[str]) -> Iterator[str]:
    raise NotImplementedError


def parse_json_lines(lines: Iterable[str], errors: list | None = None) -> Iterator[dict]:
    raise NotImplementedError


def batched(iterable: Iterable, n: int) -> Iterator[list]:
    raise NotImplementedError


def follow(path: str | Path, poll_interval: float = 0.1, max_idle_polls: int | None = None,
           sleep: Callable[[float], None] = time.sleep) -> Iterator[str]:
    raise NotImplementedError
