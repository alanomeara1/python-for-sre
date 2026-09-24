"""SSH brute-force detection from auth.log.

Same three-layer shape as the main drill: parse one line, fold many lines into an
answer. Full reasoning in EXPLAINED.md.
"""

import re
from collections import Counter
from typing import Iterable

# One pattern for both outcomes, because "Failed" and "Accepted" lines are identical
# apart from that first word. Two separate regexes would duplicate the rest.
#   (?:password|publickey)  -> (?:...) groups without capturing: we don't need the method
#   (?P<invalid>invalid user )?  -> the ? makes it optional. When it's absent the group is
#                                   None, which is exactly the boolean we want.
EVENT_RE = re.compile(
    r"sshd\[\d+\]: "                                  # anchor on sshd so CRON and other noise can't match
    r"(?P<result>Failed|Accepted) (?:password|publickey) for "
    r"(?P<invalid>invalid user )?(?P<user>\S+) "
    r"from (?P<ip>\S+) port \d+"
)


def parse_event(line: str) -> dict | None:
    # .search, not .match: a syslog timestamp and hostname come first, so the part we
    # care about never starts at column 0. (The main drill uses .match precisely because
    # its lines DO start with the field it wants.)
    match = EVENT_RE.search(line)
    if not match:
        return None
    return {
        "result": match["result"].lower(),            # normalise now so callers compare against one casing
        "user": match["user"],
        "ip": match["ip"],
        "invalid_user": match["invalid"] is not None,  # group absent -> None -> False
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

    # ONE pass building both collections. The obvious alternative, calling failures_by_ip()
    # and then looping again for the accepted IPs, reads the input twice: fine for a list,
    # silently empty on the second pass for a generator or an open file. A test covers this.
    for line in lines:
        event = parse_event(line)
        if event is None:
            continue
        if event["result"] == "failed":
            failures[event["ip"]] += 1
        else:
            # Any successful login clears the IP: it's far more likely to be a colleague on a
            # fat-fingered password than an attacker who got in.
            accepted.add(event["ip"])

    offenders = [(ip, n) for ip, n in failures.items() if n >= threshold and ip not in accepted]
    # Tuples compare left to right, so (-count, ip) means "most failures first, then IP
    # ascending to break ties". Negating sorts one key descending; reverse=True would flip
    # the tie-break too and make the output order arbitrary between equal counts.
    offenders.sort(key=lambda pair: (-pair[1], pair[0]))
    return [ip for ip, _ in offenders]
