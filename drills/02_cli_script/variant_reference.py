"""check_certs: warn before TLS certificates in an inventory expire."""

import argparse
import json
import sys
from datetime import datetime, timezone

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
NAMES = {OK: "OK", WARNING: "WARNING", CRITICAL: "CRITICAL", UNKNOWN: "UNKNOWN"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check certificate expiry from a JSON inventory.")
    parser.add_argument("inventory", help='JSON file: {"host": "ISO-8601 expiry", ...}')
    parser.add_argument("--warn-days", type=int, default=30)
    parser.add_argument("--crit-days", type=int, default=7)
    return parser


def days_left(expiry: datetime, now: datetime) -> int:
    # timedelta.days rounds down: 2 days 23 hours is 2 days, which is the safe direction.
    return (expiry - now).days


def status_for(days: int, warn_days: int, crit_days: int) -> int:
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

    try:
        with open(args.inventory, encoding="utf-8") as f:
            inventory = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"UNKNOWN - cannot read inventory: {exc}")
        return UNKNOWN

    rows = []
    for host, expiry in inventory.items():
        days = days_left(datetime.fromisoformat(expiry), now)
        rows.append((days, host, status_for(days, args.warn_days, args.crit_days)))

    # Tuples sort element by element: soonest first, then host name as a stable tiebreak.
    rows.sort()
    for days, host, code in rows:
        print(f"{NAMES[code]} {host} {days} days left")

    return max((code for _, _, code in rows), default=OK)


if __name__ == "__main__":
    sys.exit(main())
