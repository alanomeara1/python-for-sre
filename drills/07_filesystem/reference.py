"""Disk cleanup helpers: find old files, delete safely, rotate by count."""

import fnmatch
import os
import time
from pathlib import Path

SECONDS_PER_DAY = 86_400


def find_files(root, older_than_days: float, min_bytes: int = 0,
               pattern: str = "*", now: float | None = None) -> list[Path]:
    now = time.time() if now is None else now      # injectable clock for tests
    cutoff = now - older_than_days * SECONDS_PER_DAY
    matches = []

    # os.walk does not descend into symlinked directories (followlinks=False).
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not fnmatch.fnmatch(name, pattern):
                continue
            path = Path(dirpath) / name
            # is_file() is True for a link to a file, so reject links first.
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            if stat.st_mtime < cutoff and stat.st_size >= min_bytes:
                matches.append(path)

    return sorted(matches)


def cleanup(root, older_than_days: float, dry_run: bool = True,
            now: float | None = None) -> dict:
    files = find_files(root, older_than_days, now=now)
    total_bytes = sum(p.stat().st_size for p in files)   # measure BEFORE deleting

    if not dry_run:
        for path in files:
            # Another process (logrotate, the app) may have removed it since the scan.
            path.unlink(missing_ok=True)

    return {"files": files, "bytes": total_bytes, "deleted": not dry_run}


def rotate(directory, pattern: str, keep: int) -> list[Path]:
    if keep < 0:
        raise ValueError(f"keep must be >= 0, got {keep}")

    candidates = [p for p in Path(directory).glob(pattern)
                  if p.is_file() and not p.is_symlink()]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)   # newest first

    removed = candidates[keep:]
    for path in removed:
        path.unlink(missing_ok=True)
    return removed


if __name__ == "__main__":
    import sys

    report = cleanup(sys.argv[1], older_than_days=float(sys.argv[2]), dry_run="--delete" not in sys.argv)
    verb = "Deleted" if report["deleted"] else "Would delete"
    print(f"{verb} {len(report['files'])} files, {report['bytes'] / 1e6:.1f} MB")
