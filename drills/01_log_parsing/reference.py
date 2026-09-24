"""Access-log summary: totals, status codes, top IPs, 5xx error rate.

Three layers, each testable on its own: one line -> one dict, many lines -> one
report, a file -> the report. Full reasoning in EXPLAINED.md.
"""

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Compiled once at import, not per line: on a multi-GB log that cost lands a billion times.
# Named groups (?P<name>...) beat numbered ones: you read fields by name, and adding a
# field later doesn't renumber everything.
# A regex, not line.split(), because two fields contain spaces (the bracketed timestamp and
# the quoted request), which would shift every later field along.
LINE_RE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ '                     # ip, then ident and user: matched, not captured
    r'\[(?P<time>[^\]]+)\] '                     # \[ \] are escaped: bare [] means a character class.
                                                 # [^\]]+ = "anything but ]", so it stops at the bracket
    r'"(?P<method>[A-Z]+) (?P<path>\S+) \S+" '   # "GET /api/users HTTP/1.1"; protocol discarded
    r'(?P<status>\d{3}) '                        # exactly three digits
    r'(?P<bytes>\d+|-) '                         # digits OR "-", which means no response body
    r'(?P<duration>[\d.]+)'                      # a dot inside [...] is literal, no escape needed
)                                                # NOTE: each chunk ends with a space; they're
                                                 # concatenated, so a missing one matches nothing.

# A photograph of "17/Sep/2026:10:15:32 +0000". %b = short month name, %z = UTC offset.
# %z is what makes the result timezone-AWARE, so comparing it to datetime.now(timezone.utc)
# works; a naive datetime raises TypeError there.
TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


def parse_line(line: str) -> dict | None:
    # .match anchors at the start, which suits a fixed line layout.
    # (Use .search when the interesting part floats mid-line, as in the variant.)
    match = LINE_RE.match(line)
    if not match:
        # Return None rather than raise: one bad line must not kill a report over a million
        # good ones. The caller counts these instead, and a SPIKE in them is its own signal.
        return None

    record = match.groupdict()          # every value is still a str here: "200", not 200
    # Convert at the edge, so nothing downstream ever has to think about types again.
    record["time"] = datetime.strptime(record["time"], TIME_FORMAT)
    record["status"] = int(record["status"])
    # int("-") raises ValueError; "-" means no body was sent, so zero is the honest value.
    record["bytes"] = 0 if record["bytes"] == "-" else int(record["bytes"])
    record["duration"] = float(record["duration"])
    return record


def summarize(lines: Iterable[str], top_n: int = 3) -> dict:
    # Counter is a dict whose missing keys read as 0, so += needs no setup.
    status_counts = Counter()
    ip_counts = Counter()
    # Safe for ints because they're immutable: += rebinds one name and leaves the others.
    # Never do this with a mutable value (a = b = [] makes both names share one list).
    total = malformed = errors = 0

    # Iterable, not list: this accepts a list, a generator, or an open file. That's what lets
    # summarize_file() stream a huge log through constant memory.
    for line in lines:
        if not line.strip():
            # Files end with a newline; a trailing blank line is not corruption.
            continue
        record = parse_line(line)
        if record is None:
            malformed += 1
            continue                    # guard clauses keep the happy path flat and unindented

        total += 1
        status_counts[record["status"]] += 1
        ip_counts[record["ip"]] += 1
        if record["status"] >= 500:
            # 5xx only: the server broke. 4xx is usually the client's fault, and paging on
            # 404s is how a team learns to ignore its alerts.
            errors += 1

    return {
        "total": total,
        "malformed": malformed,
        "status_counts": dict(status_counts),        # plain dict: a finished result, not a live tally
        "top_ips": ip_counts.most_common(top_n),     # [(ip, count), ...], highest first
        # The guard that matters: an empty or all-garbage file would otherwise raise
        # ZeroDivisionError exactly when something is already going wrong.
        "error_rate": errors / total if total else 0.0,
    }


def summarize_file(path: str | Path, top_n: int = 3) -> dict:
    # `with` closes the handle even if summarize raises; leaked handles eventually exhaust the limit.
    # errors="replace" survives truncated or mixed-encoding logs instead of crashing on one bad byte.
    with open(path, encoding="utf-8", errors="replace") as f:
        # Passing the file object itself is the streaming trick: iterating a file yields one line
        # at a time, so memory stays flat. f.read().splitlines() would load the whole log into RAM.
        return summarize(f, top_n=top_n)


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(summarize_file(sys.argv[1]), indent=2))
