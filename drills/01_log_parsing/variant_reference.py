"""SSH brute-force detection from auth.log."""

import re
from collections import Counter
from typing import Iterable

# One regex for both outcomes. The optional group catches "invalid user ".
EVENT_RE = re.compile(
    r"sshd\[\d+\]: "
    r"(?P<result>Failed|Accepted) (?:password|publickey) for "
    r"(?P<invalid>invalid user )?(?P<user>\S+) "
    r"from (?P<ip>\S+) port \d+"
)


def parse_event(line: str) -> dict | None:
    match = EVENT_RE.search(line)       # search, not match: the timestamp prefix varies
    if not match:
        return None
    return {
        "result": match["result"].lower(),
        "user": match["user"],
        "ip": match["ip"],
        "invalid_user": match["invalid"] is not None,
    }


def failures_by_ip(lines: Iterable[str]) -> dict[str, int]:
    counts = Counter()
    for line in lines:
        event = parse_event(line)
        if event and event["result"] == "failed":
            counts[event["ip"]] += 1
    return dict(counts)


def ips_to_block(lines: Iterable[str], threshold: int = 5) -> list[str]:
    failures = Counter()
    accepted = set()

    # Single pass: the input may be a generator we can only read once.
    for line in lines:
        event = parse_event(line)
        if event is None:
            continue
        if event["result"] == "failed":
            failures[event["ip"]] += 1
        else:
            accepted.add(event["ip"])

    offenders = [(ip, n) for ip, n in failures.items() if n >= threshold and ip not in accepted]
    offenders.sort(key=lambda pair: (-pair[1], pair[0]))
    return [ip for ip, _ in offenders]
