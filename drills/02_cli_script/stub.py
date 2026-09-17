"""check_disk: Nagios-style disk usage check.

Spec: drills/02_cli_script/README.md
"""

import argparse
import logging
import shutil
import sys

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    raise NotImplementedError


def evaluate(percent_used: float, warn: float, crit: float) -> tuple[int, str]:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
