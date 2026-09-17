"""Access-log summary: totals, status codes, top IPs, 5xx error rate.

Spec: drills/01_log_parsing/README.md
"""

from pathlib import Path
from typing import Iterable


def parse_line(line: str) -> dict | None:
    raise NotImplementedError


def summarize(lines: Iterable[str], top_n: int = 3) -> dict:
    raise NotImplementedError


def summarize_file(path: str | Path, top_n: int = 3) -> dict:
    raise NotImplementedError
