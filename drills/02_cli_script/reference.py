"""check_disk: Nagios-style disk usage check.

Parser, decision, wiring: build_parser() describes the arguments, evaluate() is a pure
decision, main() wires them together and returns the exit code. Reasoning in EXPLAINED.md.
"""

import argparse
import logging
import shutil
import sys

# A NAMED logger, not the root one, so this script's verbosity can be tuned
# independently of any library's. In a package you'd use __name__.
log = logging.getLogger("check_disk")

# Exit codes are the API: the monitoring agent reads these, not the text.
# Naming them stops `return 2` appearing somewhere that meant WARNING.
OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    # A function, not module-level code: importable and testable without side effects.
    parser = argparse.ArgumentParser(description="Check disk usage against thresholds.")
    parser.add_argument("--path", default="/", help="mount point to check (default: /)")
    # type=float matters: without it argparse hands you strings, and "85" >= "9" compares
    # text and is silently False.
    parser.add_argument("-w", "--warn", type=float, default=80.0, help="warning at this percent used")
    parser.add_argument("-c", "--crit", type=float, default=90.0, help="critical at this percent used")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    return parser


def evaluate(percent_used: float, warn: float, crit: float) -> tuple[int, str]:
    # Check the most severe level first, so the first match wins. The conditions overlap
    # (95% is over both thresholds); reverse these and everything critical reports as a warning.
    if percent_used >= crit:
        return CRITICAL, "CRITICAL"
    # >= not >: at exactly 90% you want the page, not an argument about boundaries.
    if percent_used >= warn:
        return WARNING, "WARNING"
    return OK, "OK"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)          # argv=None means "use sys.argv"; tests pass a list
    # Cross-argument validation belongs here: argparse can check one argument's type, not a
    # relationship between two. parser.error() prints usage to stderr and exits 2.
    if args.warn >= args.crit:
        parser.error("--warn must be lower than --crit")

    # Logs go to stderr so they never pollute the one status line on stdout, which is what the
    # monitoring agent parses. basicConfig is a no-op if the root logger already has handlers,
    # so call it once, early.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        # shutil.disk_usage, not `from shutil import disk_usage`: tests (and real mocks) patch
        # the attribute on the module, which a local copy of the function would ignore.
        usage = shutil.disk_usage(args.path)
    except OSError as exc:
        # "Couldn't check" is not "OK". Surface it as UNKNOWN.
        # OSError covers FileNotFoundError, PermissionError and friends, while a real bug in
        # this script still crashes loudly instead of being swallowed.
        print(f"DISK UNKNOWN - {args.path}: {exc}")
        return UNKNOWN

    percent = usage.used / usage.total * 100
    # %s placeholders, not an f-string: logging formats only if the message is actually emitted,
    # and aggregators can group on the structured arguments.
    log.debug("path=%s total=%d used=%d percent=%.2f", args.path, usage.total, usage.used, percent)

    code, name = evaluate(percent, args.warn, args.crit)
    # One line, stable shape, one decimal place. stdout belongs to the agent.
    print(f"DISK {name} - {args.path} {percent:.1f}% used")
    return code


if __name__ == "__main__":
    # main() returns the code rather than exiting, so it stays testable; this line is the only
    # place that touches the process.
    sys.exit(main())
