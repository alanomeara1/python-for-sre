"""check_disk: Nagios-style disk usage check."""

import argparse
import logging
import shutil
import sys

log = logging.getLogger("check_disk")

# Exit codes are the API: the monitoring agent reads these, not the text.
OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check disk usage against thresholds.")
    parser.add_argument("--path", default="/", help="mount point to check (default: /)")
    parser.add_argument("-w", "--warn", type=float, default=80.0, help="warning at this percent used")
    parser.add_argument("-c", "--crit", type=float, default=90.0, help="critical at this percent used")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    return parser


def evaluate(percent_used: float, warn: float, crit: float) -> tuple[int, str]:
    # Check the most severe level first, so the first match wins.
    if percent_used >= crit:
        return CRITICAL, "CRITICAL"
    if percent_used >= warn:
        return WARNING, "WARNING"
    return OK, "OK"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)          # argv=None means "use sys.argv"; tests pass a list
    if args.warn >= args.crit:
        parser.error("--warn must be lower than --crit")

    # Logs go to stderr so they never pollute the one status line on stdout.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        usage = shutil.disk_usage(args.path)
    except OSError as exc:
        # "Couldn't check" is not "OK". Surface it as UNKNOWN.
        print(f"DISK UNKNOWN - {args.path}: {exc}")
        return UNKNOWN

    percent = usage.used / usage.total * 100
    log.debug("path=%s total=%d used=%d percent=%.2f", args.path, usage.total, usage.used, percent)

    code, name = evaluate(percent, args.warn, args.crit)
    print(f"DISK {name} - {args.path} {percent:.1f}% used")
    return code


if __name__ == "__main__":
    sys.exit(main())
