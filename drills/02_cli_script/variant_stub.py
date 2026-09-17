"""check_certs: warn before TLS certificates in an inventory expire.

Spec: drills/02_cli_script/variant.md
"""

import argparse
import json
import sys
from datetime import datetime, timezone

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
NAMES = {OK: "OK", WARNING: "WARNING", CRITICAL: "CRITICAL", UNKNOWN: "UNKNOWN"}


def build_parser() -> argparse.ArgumentParser:
    raise NotImplementedError


def days_left(expiry: datetime, now: datetime) -> int:
    raise NotImplementedError


def status_for(days: int, warn_days: int, crit_days: int) -> int:
    raise NotImplementedError


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
