"""Streaming log toolkit: lazy read, grep, JSON lines, batching, tail -f."""

import json
import os
import re
import time
from itertools import islice
from pathlib import Path
from typing import Callable, Iterable, Iterator


def read_lines(path: str | Path) -> Iterator[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:                  # one line in memory at a time
            yield line.rstrip("\n")


def grep(pattern: str, lines: Iterable[str]) -> Iterator[str]:
    regex = re.compile(pattern)         # compile once, not per line
    for line in lines:
        if regex.search(line):
            yield line


def parse_json_lines(lines: Iterable[str], errors: list | None = None) -> Iterator[dict]:
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        if not isinstance(record, dict):
            # Report bad lines to the caller rather than crash or silently drop them.
            if errors is not None:
                errors.append((number, line))
            continue
        yield record


def batched(iterable: Iterable, n: int) -> Iterator[list]:
    if n < 1:
        raise ValueError("n must be at least 1")
    it = iter(iterable)                 # without this, islice on a list restarts at item 0 forever
    while batch := list(islice(it, n)):
        yield batch


def follow(path: str | Path, poll_interval: float = 0.1, max_idle_polls: int | None = None,
           sleep: Callable[[float], None] = time.sleep) -> Iterator[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)          # like tail -f: only lines written from now on
        partial = ""
        idle_polls = 0
        while True:
            chunk = f.readline()
            if chunk:
                idle_polls = 0
                partial += chunk
                if partial.endswith("\n"):          # hold back half-written lines
                    yield partial.rstrip("\n")
                    partial = ""
                continue
            if max_idle_polls is not None and idle_polls >= max_idle_polls:
                return
            idle_polls += 1
            sleep(poll_interval)
