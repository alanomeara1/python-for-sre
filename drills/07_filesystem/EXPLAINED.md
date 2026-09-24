# 07 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

This is the drill where the wrong version deletes a production filesystem, so almost every
decision here is about **safety**, not cleverness.

---

## The mental model

```
find_files(...)   decide WHAT matches      → returns paths, changes nothing
cleanup(...)      decide whether to ACT    → dry run by default
rotate(...)       keep the newest K        → a different question: count, not age
```

The separation is the whole design: **finding is pure, deleting is a separate, explicit step.**
That's what lets you run the finder in anger at 3am and look at the list before anything is
destroyed, and it's what the interviewer is really testing.

**Memory hook: find → report → (only if told) delete.**

`rotate` is deliberately a different shape, because "keep the newest 7 backups" is a *count*
question. Age-based cleanup deletes everything when a job has been broken for a month; count-based
retention always leaves you something.

---

## Chunk 1: The clock and the cutoff

```python
SECONDS_PER_DAY = 86_400

def find_files(root, older_than_days: float, min_bytes: int = 0,
               pattern: str = "*", now: float | None = None) -> list[Path]:
    now = time.time() if now is None else now      # injectable clock for tests
    cutoff = now - older_than_days * SECONDS_PER_DAY
```

**Why `now` is a parameter:** file times are epoch seconds, and a test that wants "a file 20 days
old" would otherwise have to either sleep or monkeypatch `time.time`. Passing `now` in makes the
tests exact, instant and readable. This is dependency injection in its cheapest form, and the same
trick as the `sleep=` parameter in drill 04 and `now=` in drill 08.

**Why `None` as the default rather than `time.time()` in the signature:** default arguments are
evaluated **once, at function definition**. `def find_files(now=time.time())` would freeze the
clock at import time, and the function would drift further from reality the longer the process
ran. The `None` sentinel is the standard fix, and the same reason you write
`def f(items=None): items = items or []` instead of `def f(items=[])`.

**Why a named constant:** `older_than_days * 86400` in the middle of an expression is where the
conversion gets forgotten, and forgetting it means nothing is ever old enough to delete, so the
script silently does nothing forever. Naming it makes the units visible.

**Why compute `cutoff` once, before the loop:** it's loop-invariant. Computing it per file would
also mean a file's fate depended on when the walk reached it.

**Rebuild it from first principles:** "old" means the modification time is before some instant.
Work out that instant once, then compare each file's `st_mtime` to it.

---

## Chunk 2: The walk

```python
    # os.walk does not descend into symlinked directories (followlinks=False).
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
```

**Why `os.walk` and not `Path.rglob`:** before Python 3.13, `rglob`/`**` descended into symlinked
directories, so a link like `logs/archive -> /` would walk your entire root filesystem and offer it
all up for deletion. `os.walk` takes `followlinks=False` by default, and behaves the same on every
version. Python 3.13 added `recurse_symlinks` to `rglob` and made not-following the default, but
`os.walk` remains the version-independent, obviously-safe choice. Say the version caveat out loud
rather than claiming `rglob` is simply broken.

**Why `_dirnames` with an underscore:** the tuple has three elements and you only need two. The
underscore prefix is the convention for "deliberately unused", so a reader doesn't hunt for where
it's used. (You *could* mutate `dirnames` in place to prune the walk, which is a genuinely useful
trick: `dirnames[:] = [d for d in dirnames if d != ".git"]`.)

**Why `filenames` is only names:** `os.walk` gives you the directory path and bare names
separately, which is why the next step rebuilds the full path with `Path(dirpath) / name`.

---

## Chunk 3: The filters, in the order they appear

```python
            if not fnmatch.fnmatch(name, pattern):
                continue
            path = Path(dirpath) / name
            # is_file() is True for a link to a file, so reject links first.
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            if stat.st_mtime < cutoff and stat.st_size >= min_bytes:
                matches.append(path)
```

**Why `fnmatch` rather than a regex:** it implements shell glob semantics (`*.log*`), which is what
a person means when they say "pattern" about filenames, and it's what `ls` and `find -name` use.
The check is on `name`, not the full path, matching `find -name` rather than `find -path`.

**Why the symlink check comes before `is_file()`:** `Path.is_file()` follows the link and reports on
the *target*. A symlink pointing at a real file therefore passes `is_file()`, and you'd delete the
link (or worse, count the target's size as reclaimable when deleting the link frees nothing).
Checking `is_symlink()` first is the only correct order. The test builds both a link to a file and
a link to a directory outside the tree, and asserts neither shows up.

**Why `not path.is_file()` at all:** the walk only yields filenames, but the entry could be a
socket, a FIFO or a device node, and it could disappear between the walk and the check.
`is_file()` returns False rather than raising if the path has vanished.

**Why one `stat()` call into a variable:** each `path.stat()` is a syscall. Calling it twice, once
for `st_mtime` and once for `st_size`, doubles the syscalls on a directory with millions of files
and introduces a window where the two values describe different states of the file.

**Why `<` for time but `>=` for size:** "older than 7 days" means strictly before the cutoff;
"at least min_bytes" includes the boundary, and the default `min_bytes=0` must match every file,
which `>= 0` does and `> 0` would not (an empty file is still a file).

**Why `sorted(matches)`:** `os.walk` order depends on the filesystem, so without it the output
differs between runs and machines. `Path` sorts lexicographically, which gives deterministic,
diffable output and lets the test assert an exact list.

---

## Chunk 4: `cleanup`, where the safety lives

```python
def cleanup(root, older_than_days: float, dry_run: bool = True,
            now: float | None = None) -> dict:
    files = find_files(root, older_than_days, now=now)
    total_bytes = sum(p.stat().st_size for p in files)   # measure BEFORE deleting

    if not dry_run:
        for path in files:
            # Another process (logrotate, the app) may have removed it since the scan.
            path.unlink(missing_ok=True)

    return {"files": files, "bytes": total_bytes, "deleted": not dry_run}
```

**Why `dry_run=True` is the default, and why that's the headline:** the mode you get by *accident*
should be the safe one. Anyone who calls `cleanup(path, 7)` having skimmed the signature gets a
report, not a deletion. To destroy data you have to type `dry_run=False`, which is a decision you
can see in a code review and in a git diff.

**Why measure bytes before deleting:** `p.stat()` on a deleted file raises `FileNotFoundError`.
Beyond that, the number you report is "what this run reclaimed", which only exists before the
unlink. Getting this order wrong is the most common way to break this function.

**Why `missing_ok=True`:** between the scan and the delete, logrotate, the application, or another
copy of your own script may have removed the file. That's a race you cannot eliminate, only absorb.
The alternative, wrapping each unlink in `try/except FileNotFoundError`, is the same thing spelled
longer. Note it doesn't protect against permission errors, which you *do* want to hear about.

**Why return a dict instead of printing:** the caller formats. The `__main__` block turns it into
"Would delete 3 files, 14.3 MB", a monitoring script might emit the byte count as a metric, and a
test asserts on the values. A function that prints can only ever do one of those.

**Why `"deleted": not dry_run` is in the return:** whoever reads the report shouldn't have to
remember which mode they asked for. It makes the log line ("Deleted" vs "Would delete") honest.

**Worth saying out loud:** deleting a log file that a process still holds open frees nothing until
the process closes it, because the inode survives while the file descriptor lives. `lsof +L1`
shows them. Often the right fix is truncating (`: > file`) or restarting the writer, and the real
long-term fix is logrotate or shipping logs off the box rather than a cron job running this.

---

## Chunk 5: `rotate`, a count-based question

```python
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
```

**Why validate `keep` first, before touching the filesystem:** `candidates[-1:]` is valid Python
and would silently delete only the *oldest* file, which is precisely backwards. Fail loudly on
impossible input before doing anything destructive. This is the "raise rather than return a
misleading result" principle: a negative `keep` is a bug in the caller, not a weird edge case.

**Why `glob` and not `os.walk`:** rotation is per-directory by definition. `logs/app.log.1` and
`logs/old/app.log.1` are different rotations, and recursing would mix them and delete the wrong
ones.

**Why sort newest first, then slice `[keep:]`:** the slice reads exactly like the requirement,
"everything after the newest K". Sorting oldest-first and taking `[:-keep]` works until `keep` is
0, where `[:-0]` is the empty list and you'd delete nothing when asked to delete everything. The
`[keep:]` form handles `keep=0` (delete all) and `keep > len(candidates)` (delete nothing) with no
special cases, and both are tested.

**Why `key=lambda p: p.stat().st_mtime`:** sorting by name is the obvious-looking mistake.
`backup-10.tar` sorts before `backup-9.tar` lexicographically, so a name-sorted rotation deletes
the wrong files as soon as you reach double digits.

**Why `reverse=True` rather than negating the key:** mtimes are floats, so `key=lambda p:
-p.stat().st_mtime` would also work, but `reverse=True` states the intent and doesn't rely on the
key being numeric.

**Why return the removed paths:** the caller logs or asserts on them. The test relies on the order
being newest-first, which falls out of the sort.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_find_files_age_recursive_sorted` | forgot `* SECONDS_PER_DAY`, used `>` instead of `<` on mtime, or didn't sort |
| `test_find_files_min_bytes_and_pattern` | matched the whole path instead of the name, or used `>` for `min_bytes` |
| `test_find_files_skips_symlinks` | checked `is_file()` before `is_symlink()`, or used `rglob` and followed a linked directory |
| `test_find_files_default_now_uses_real_clock` | made `now` mandatory, or froze it as a default argument value |
| `test_cleanup_dry_run_deletes_nothing` | `dry_run` isn't defaulting to True, or you deleted before checking it |
| `test_cleanup_for_real` | measured bytes after deleting, or followed the symlinked directory and deleted outside the tree |
| `test_rotate_keeps_newest` | sorted by name rather than mtime, or sliced the wrong end |
| `test_rotate_edge_cases` | `keep=0` didn't delete everything (the `[:-keep]` trap), or no `ValueError` on a negative `keep` |

`FileNotFoundError` from `stat()` means you measured sizes after the unlink loop.

---

## The variant: what actually changes

Grandfather-father-son retention is the same *decision* ("what is safe to delete?") with the
filesystem removed entirely. It's a pure function over filenames, which is why it can be tested
exhaustively. Five ideas:

1. **Compute the keep set, then delete the complement.** Retention is a union of rules, and a
   backup survives if *any* rule keeps it. Trying to decide "should I delete this one?" file by
   file means re-deriving every rule per file and getting the overlaps wrong. A Sunday that's also
   in the last 7 days is kept by both, and a union handles that for free.

2. **"Last N" means the N most recent that exist, not a calendar window.** This is the operational
   heart of the drill. If the backup job broke three weeks ago, a calendar window ("keep anything
   from the last 7 days") keeps *nothing* and deletes every backup you have, at exactly the moment
   you need one. Sorting the dates you actually have and taking the first N is the safe reading.

3. **Two-stage validation: shape, then reality.** `BACKUP_RE` proves the filename looks like
   `db-YYYY-MM-DD.sql.gz`; `date.fromisoformat` proves the date exists. A regex can't tell you that
   `2026-02-30` isn't a day, which is why the `try/except ValueError` is there rather than a
   cleverer pattern.

4. **Unrecognised names are never returned.** `notes.txt`, `db-2026-09-01.sql.gz.tmp` (a partial
   upload) and anything else are skipped. The safe failure mode for a retention script is using
   too much storage, never deleting a file whose purpose you don't understand.

5. **Future-dated backups are left alone and don't use a slot.** Clock skew and timezone bugs
   produce them, and a file dated tomorrow shouldn't push a real backup out of the "last 7".

The mechanics worth noticing: `backups[day] = name` in a dict de-duplicates two files claiming the
same date and gives you dates as keys to sort; `date.weekday()` returns 0 for Monday, so Sunday is
6; and the final `sorted(...)` returns oldest-first for a stable, readable delete list.
