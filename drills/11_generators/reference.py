"""Streaming log toolkit: lazy read, grep, JSON lines, batching, tail -f.

Every stage takes an iterable and yields, so nothing runs until someone iterates
and memory is one line plus one batch -- whatever the file size, and even when the
source never ends. Full reasoning in EXPLAINED.md.
"""

import json
import os
import re
import time
from itertools import islice
from pathlib import Path
from typing import Callable, Iterable, Iterator


def read_lines(path: str | Path) -> Iterator[str]:
    # `with` inside a generator holds the file open across yields and closes it when the
    # generator is exhausted -- or, if the consumer breaks early, when it is collected and
    # GeneratorExit fires at the yield. (That timing is a CPython detail; an explicit
    # .close() on the generator is the belt-and-braces version.)
    with open(path, encoding="utf-8", errors="replace") as f:
        # A file object IS an iterator of lines, buffered by the OS.
        # f.read().splitlines() would load the whole log and defeat the point.
        for line in f:                  # one line in memory at a time
            # rstrip("\n"), never .strip(): stripping all whitespace silently reindents content.
            yield line.rstrip("\n")


def grep(pattern: str, lines: Iterable[str]) -> Iterator[str]:
    regex = re.compile(pattern)         # compile once, not per line
    for line in lines:
        # search, not match: match anchors at the start, and grep means "anywhere in the line".
        if regex.search(line):
            yield line


def parse_json_lines(lines: Iterable[str], errors: list | None = None) -> Iterator[dict]:
    # start=1 because editors and sed count from 1; a bug report saying "line 0" wastes time.
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue                    # a trailing newline at end of file is not corruption
        try:
            record = json.loads(line)
        # The specific exception. A bare `except:` would also swallow KeyboardInterrupt,
        # so Ctrl-C would stop working on a long pipeline run.
        except json.JSONDecodeError:
            record = None
        # "[1, 2, 3]" and "42" are VALID json and are not log records. Without this check they
        # sail through and blow up in a later stage, far away from the line that caused it.
        if not isinstance(record, dict):
            # Report bad lines to the caller rather than crash or silently drop them.
            # An error channel, not a policy: the caller decides whether 3 bad lines in a
            # million is routine or whether a spike means the log format changed upstream.
            if errors is not None:
                errors.append((number, line))
            continue
        yield record


def batched(iterable: Iterable, n: int) -> Iterator[list]:
    # n=0 would make islice yield nothing, so the loop would exit at once and the job would
    # "succeed" having shipped no data. Fail loudly instead.
    if n < 1:
        raise ValueError("n must be at least 1")
    # THE line of this function. A list is iterable but not an iterator: every islice() call
    # asks it for a fresh one starting at item 0, so the loop would re-yield the first n items
    # forever. iter() fixes a single position that each islice resumes from. Harmless on a
    # generator, because iter() on an iterator returns it unchanged.
    it = iter(iterable)                 # without this, islice on a list restarts at item 0 forever
    # list() is required: a bare islice object is always truthy, so the loop would never end.
    # Empty list = source exhausted = falsy = stop.
    while batch := list(islice(it, n)):
        yield batch


def follow(path: str | Path, poll_interval: float = 0.1, max_idle_polls: int | None = None,
           sleep: Callable[[float], None] = time.sleep) -> Iterator[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        # "0 bytes relative to the end" -- the definition of tail -f. You want what happens
        # next, not the existing 40GB.
        f.seek(0, os.SEEK_END)          # like tail -f: only lines written from now on
        partial = ""
        idle_polls = 0
        while True:
            # readline(), not `for line in f`: the file iterator read-aheads and doesn't cope
            # with a file that keeps growing. readline() returns "" at EOF and works again later.
            chunk = f.readline()
            if chunk:
                idle_polls = 0          # consecutive, so any data resets the countdown
                # A writer may flush "partial" and only later write " done\n". readline()
                # returns that fragment with no newline, so emitting it would hand downstream
                # two broken records. Accumulate until the terminating newline arrives.
                partial += chunk
                if partial.endswith("\n"):          # hold back half-written lines
                    yield partial.rstrip("\n")
                    partial = ""
                continue
            # Checked BEFORE the increment and the sleep, which is what makes max_idle_polls=3
            # produce exactly three sleeps. None = follow forever, the production behaviour.
            if max_idle_polls is not None and idle_polls >= max_idle_polls:
                return
            idle_polls += 1
            # sleep is a parameter so tests stay instant and deterministic: the test's fake
            # sleep appends to the file, simulating a live writer with no thread and no race.
            # Any loop that waits becomes testable by injecting the waiter.
            sleep(poll_interval)
            # Honest limitation: no rotation handling. After logrotate renames the file this
            # keeps reading the old inode, and it never notices a truncation. tail -F re-stats
            # the path and reopens on inode change or shrink; in production, ship with Fluent
            # Bit or Vector rather than maintain that here.
