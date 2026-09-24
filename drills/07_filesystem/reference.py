"""Disk cleanup helpers: find old files, delete safely, rotate by count.

Finding is pure and deletion is a separate, explicit step, so you can run the
finder in anger at 3am and read the list before anything is destroyed.
Full reasoning in EXPLAINED.md.
"""

import fnmatch
import os
import time
from pathlib import Path

# Named, because "older_than_days * 86400" buried in an expression is where the
# conversion gets forgotten, and then nothing is ever old enough to delete.
SECONDS_PER_DAY = 86_400


def find_files(root, older_than_days: float, min_bytes: int = 0,
               pattern: str = "*", now: float | None = None) -> list[Path]:
    # None sentinel, not now=time.time() in the signature: default arguments are
    # evaluated once at import, so that would freeze the clock for the process lifetime.
    now = time.time() if now is None else now      # injectable clock for tests
    cutoff = now - older_than_days * SECONDS_PER_DAY   # loop-invariant: compute once
    matches = []

    # os.walk does not descend into symlinked directories (followlinks=False).
    # Path.rglob did follow them before Python 3.13, so "logs/archive -> /" would
    # offer the whole root filesystem up for deletion. os.walk is the same everywhere.
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            # fnmatch is shell glob semantics on the NAME, like find -name, which is
            # what a person means by "pattern" for files.
            if not fnmatch.fnmatch(name, pattern):
                continue
            path = Path(dirpath) / name
            # is_file() is True for a link to a file, so reject links first.
            # Deleting a link frees nothing, and its target may live outside root.
            if path.is_symlink() or not path.is_file():
                continue
            # One stat() into a variable: two calls double the syscalls and can see
            # two different states of the same file.
            stat = path.stat()
            # < for age (strictly older than the cutoff), >= for size so that the
            # default min_bytes=0 still matches empty files.
            if stat.st_mtime < cutoff and stat.st_size >= min_bytes:
                matches.append(path)

    # os.walk order is filesystem-dependent; sorting makes runs comparable and diffable.
    return sorted(matches)


def cleanup(root, older_than_days: float, dry_run: bool = True,
            now: float | None = None) -> dict:
    files = find_files(root, older_than_days, now=now)
    # stat() on a deleted file raises, and the number worth reporting is what this run
    # reclaimed, which only exists while the files do.
    total_bytes = sum(p.stat().st_size for p in files)   # measure BEFORE deleting

    # dry_run defaults to True because the mode you get by ACCIDENT should be the safe
    # one: destroying data requires typing dry_run=False, visible in review and in diffs.
    if not dry_run:
        for path in files:
            # Another process (logrotate, the app) may have removed it since the scan.
            # An unavoidable race, absorbed rather than crashed on. Permission errors
            # still raise, which is what you want.
            path.unlink(missing_ok=True)

    # Return data, don't print: the caller formats, a metric exporter counts, a test asserts.
    # "deleted" tells the reader which mode actually ran, so the log line stays honest.
    return {"files": files, "bytes": total_bytes, "deleted": not dry_run}


def rotate(directory, pattern: str, keep: int) -> list[Path]:
    # Validate before touching the filesystem: candidates[-1:] is valid Python and would
    # delete only the oldest file, exactly backwards. Impossible input is a caller bug.
    if keep < 0:
        raise ValueError(f"keep must be >= 0, got {keep}")

    # glob, not walk: rotation is per-directory. logs/app.log.1 and logs/old/app.log.1
    # are separate rotations and must not be mixed.
    candidates = [p for p in Path(directory).glob(pattern)
                  if p.is_file() and not p.is_symlink()]
    # By mtime, never by name: "backup-10.tar" sorts before "backup-9.tar".
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)   # newest first

    # [keep:] reads as "everything after the newest K" and needs no special cases:
    # keep=0 deletes all, keep > len deletes none. Sorting oldest-first and slicing
    # [:-keep] breaks at keep=0, where [:-0] is empty and deletes nothing.
    removed = candidates[keep:]
    for path in removed:
        path.unlink(missing_ok=True)
    return removed


if __name__ == "__main__":
    import sys

    # Deleting requires an explicit flag here too, for the same reason as the default.
    report = cleanup(sys.argv[1], older_than_days=float(sys.argv[2]), dry_run="--delete" not in sys.argv)
    verb = "Deleted" if report["deleted"] else "Would delete"
    print(f"{verb} {len(report['files'])} files, {report['bytes'] / 1e6:.1f} MB")
