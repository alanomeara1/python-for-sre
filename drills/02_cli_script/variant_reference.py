"""check_certs: warn before TLS certificates in an inventory expire.

Same CLI skeleton as check_disk, but the clock is injectable, the input is a file that can
fail to load, and N hosts collapse into one exit code. Reasoning in EXPLAINED.md.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
# Per-host lines need the label as well as the code, so keep the mapping in one place.
NAMES = {OK: "OK", WARNING: "WARNING", CRITICAL: "CRITICAL", UNKNOWN: "UNKNOWN"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check certificate expiry from a JSON inventory.")
    # Positional: the inventory isn't optional, so don't pretend it has a default.
    parser.add_argument("inventory", help='JSON file: {"host": "ISO-8601 expiry", ...}')
    parser.add_argument("--warn-days", type=int, default=30)
    parser.add_argument("--crit-days", type=int, default=7)
    return parser


def days_left(expiry: datetime, now: datetime) -> int:
    # timedelta.days rounds down: 2 days 23 hours is 2 days, which is the safe direction.
    # Erring early is right for expiry; erring late means finding out from a customer.
    return (expiry - now).days


def status_for(days: int, warn_days: int, crit_days: int) -> int:
    # Mirror image of the disk check: there, higher was worse; here, FEWER days is worse.
    # Same shape, flipped comparison, which is exactly where this gets typed wrong.
    if days <= crit_days:
        return CRITICAL
    if days <= warn_days:
        return WARNING
    return OK


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.crit_days >= args.warn_days:
        parser.error("--crit-days must be lower than --warn-days")

    now = now or datetime.now(timezone.utc)       # injectable clock
    # Anything that reads the wall clock is untestable until the time can be passed in.
    # Production passes nothing; tests pin a fixed instant and get deterministic output.

    try:
        with open(args.inventory, encoding="utf-8") as f:
            inventory = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        # Two failure modes, one meaning: no data, so no opinion. Never report OK here.
        print(f"UNKNOWN - cannot read inventory: {exc}")
        return UNKNOWN

    rows = []
    for host, expiry in inventory.items():
        # fromisoformat keeps the offset from the string, so both sides of the subtraction
        # are timezone-aware and the comparison is legal.
        days = days_left(datetime.fromisoformat(expiry), now)
        rows.append((days, host, status_for(days, args.warn_days, args.crit_days)))

    # Tuples sort element by element: soonest first, then host name as a stable tiebreak.
    # Deterministic output is what makes a check safe to diff or feed to another tool.
    rows.sort()
    for days, host, code in rows:
        print(f"{NAMES[code]} {host} {days} days left")

    # One exit code for N hosts: the worst one wins, because the codes ascend by severity.
    # default=OK covers the empty inventory, since max([]) raises ValueError.
    return max((code for _, _, code in rows), default=OK)


if __name__ == "__main__":
    sys.exit(main())
