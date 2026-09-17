"""Access-log summary: totals, status codes, top IPs, 5xx error rate."""

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Compile once at import time, not per line.
# Named groups (?P<name>...) mean we read fields by name, not by position.
LINE_RE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ '                     # ip, ident, user
    r'\[(?P<time>[^\]]+)\] '                     # [17/Sep/2026:10:15:32 +0000]
    r'"(?P<method>[A-Z]+) (?P<path>\S+) \S+" '   # "GET /api/users HTTP/1.1"
    r'(?P<status>\d{3}) '
    r'(?P<bytes>\d+|-) '
    r'(?P<duration>[\d.]+)'
)

TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


def parse_line(line: str) -> dict | None:
    match = LINE_RE.match(line)
    if not match:
        return None

    record = match.groupdict()          # every value is still a str here
    # Convert types at the edge, so everything downstream gets real ints, floats and datetimes.
    record["time"] = datetime.strptime(record["time"], TIME_FORMAT)
    record["status"] = int(record["status"])
    record["bytes"] = 0 if record["bytes"] == "-" else int(record["bytes"])
    record["duration"] = float(record["duration"])
    return record


def summarize(lines: Iterable[str], top_n: int = 3) -> dict:
    status_counts = Counter()
    ip_counts = Counter()
    total = malformed = errors = 0

    for line in lines:                  # works on a list, a file, or a generator
        if not line.strip():
            continue
        record = parse_line(line)
        if record is None:
            malformed += 1
            continue

        total += 1
        status_counts[record["status"]] += 1
        ip_counts[record["ip"]] += 1
        if record["status"] >= 500:
            errors += 1

    return {
        "total": total,
        "malformed": malformed,
        "status_counts": dict(status_counts),
        "top_ips": ip_counts.most_common(top_n),
        "error_rate": errors / total if total else 0.0,
    }


def summarize_file(path: str | Path, top_n: int = 3) -> dict:
    # A file object iterates line by line, so memory stays flat on a multi-GB log.
    with open(path, encoding="utf-8", errors="replace") as f:
        return summarize(f, top_n=top_n)


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(summarize_file(sys.argv[1]), indent=2))
