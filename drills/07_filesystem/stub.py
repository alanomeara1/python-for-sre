"""Disk cleanup helpers: find old files, delete safely, rotate by count.

Spec: drills/07_filesystem/README.md
"""

from pathlib import Path


def find_files(root, older_than_days: float, min_bytes: int = 0,
               pattern: str = "*", now: float | None = None) -> list[Path]:
    raise NotImplementedError


def cleanup(root, older_than_days: float, dry_run: bool = True,
            now: float | None = None) -> dict:
    raise NotImplementedError


def rotate(directory, pattern: str, keep: int) -> list[Path]:
    raise NotImplementedError
