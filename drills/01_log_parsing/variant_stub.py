"""SSH brute-force detection from auth.log.

Spec: drills/01_log_parsing/variant.md
"""

from typing import Iterable


def parse_event(line: str) -> dict | None:
    raise NotImplementedError


def failures_by_ip(lines: Iterable[str]) -> dict[str, int]:
    raise NotImplementedError


def ips_to_block(lines: Iterable[str], threshold: int = 5) -> list[str]:
    raise NotImplementedError
