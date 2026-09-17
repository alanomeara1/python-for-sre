# 07 · Filesystem cleanup: old files, dry runs, log rotation

**Why this drill:** "The disk is at 95%, write something to clean up" is the classic on-call
script, and a favourite interview question because the dangerous version is so easy to write.
The interviewer is watching for safety: dry-run by default, no following symlinks, and no
crash when a file disappears mid-run.

## The task, as an interviewer would say it

> Our log directory keeps filling the disk. Write a function that finds files older than N days
> (optionally bigger than some size), and a cleanup that reports how many bytes it would free.
> It should only delete when explicitly told to. Also write a rotate function that keeps the
> newest K files matching a pattern and deletes the rest.

## Contract (what the tests call)

```python
def find_files(root, older_than_days: float, min_bytes: int = 0,
               pattern: str = "*", now: float | None = None) -> list[Path]
    # regular files under root (recursive) whose NAME matches pattern (fnmatch),
    # mtime strictly older than now - older_than_days, size >= min_bytes.
    # Symlinks are skipped: never follow a link to a file or directory.
    # `now` is epoch seconds; None means time.time(). Returns a sorted list.

def cleanup(root, older_than_days: float, dry_run: bool = True,
            now: float | None = None) -> dict
    # -> {"files": [Path, ...], "bytes": int, "deleted": bool}
    # "deleted" is True only when dry_run is False.

def rotate(directory, pattern: str, keep: int) -> list[Path]
    # Non-recursive. Among regular files in `directory` matching the glob `pattern`,
    # keep the newest `keep` by mtime and delete the rest.
    # Returns the removed paths, newest first. keep < 0 -> ValueError.
```

## Patterns you are drilling

- `os.walk(root)`: yields `(dirpath, dirnames, filenames)` and does **not** follow symlinked directories by default
- `fnmatch.fnmatch(name, pattern)` for shell-style matching on a name
- `path.stat().st_mtime`, `.st_size`; `path.is_symlink()` checked **before** `path.is_file()`
- A `now=None` parameter so tests (and you) can control time
- `dry_run=True` as the default. The safe mode is the one you get by accident.
- `path.unlink(missing_ok=True)`
- `sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[keep:]`

## Say this out loud (what the interviewer listens for)

- "Dry run is the default. You have to opt in to deleting."
- "I skip symlinks. A link to `/` inside the log directory must not make me delete the host."
- "I take `now` as a parameter, so this is testable without sleeping or faking the clock."
- "`missing_ok=True`, because logrotate or the app might remove the file between my scan and my delete."
- "Before deleting logs, I'd check whether a process still holds them open. Deleting an open file
  frees nothing until the process closes it (`lsof +L1`). Often the right fix is to truncate or restart."
- "Long term, the fix is logrotate or shipping logs off-box, not a cron job running this."

## Traps

- `path.is_file()` is `True` for a symlink *to* a file, so check `is_symlink()` first.
- `Path.rglob` followed symlinked directories before Python 3.13. `os.walk` is explicit and the same on every version.
- `older_than_days * 86400`: forget the conversion and nothing is ever old.
- Computing `bytes` *after* deleting: `stat()` on a deleted file raises.
- `rotate` with `keep=0` should remove everything, and `keep` larger than the file count removes nothing.
