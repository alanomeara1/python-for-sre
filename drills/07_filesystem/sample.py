"""Run the drill 07 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
the clock is injected, every mtime is fixed, and paths print relative to the
temporary root so the tmp directory name never reaches the page.
"""

import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

# A fixed "now", tz-aware so .timestamp() means the same thing on every machine.
NOW = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc).timestamp()
DAY = 86_400

# (path, age in days, size in bytes)
TREE = [
    ("app.log", 60, 250_000),
    ("debug.log", 45, 2_000),
    ("recent.log", 2, 300_000),
    ("archive/old.log", 90, 150_000),
    ("app.log.1", 1, 1_000),
    ("app.log.2", 2, 1_000),
    ("app.log.3", 3, 1_000),
    ("app.log.4", 4, 1_000),
    ("app.log.5", 5, 1_000),
]


def build(root: Path) -> None:
    for name, age_days, size in TREE:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        mtime = NOW - age_days * DAY
        os.utime(path, (mtime, mtime))      # fixed mtime: the whole drill turns on age


def listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


tmp = tempfile.TemporaryDirectory()
root = Path(tmp.name)
build(root)

print("## The main problem: finding and cleaning old files\n")
print("A log directory as it looks at 2026-09-17 10:00 UTC (sizes and ages are fixed so this\n"
      "page is reproducible):\n")
print("```text")
for name, age_days, size in TREE:
    print(f"{name:<16} {size:>9,} bytes   {age_days:>3} days old")
print("```\n")

print("`find_files(root, older_than_days=30, min_bytes=100_000)`:\n")
print("```python")
found = reference.find_files(root, older_than_days=30, min_bytes=100_000, now=NOW)
for path in found:
    print(path.relative_to(root))
print("```\n")

print("Reading that: two of the nine. `debug.log` is old enough but too small to be worth\n"
      "deleting, and `recent.log` is big but current. Both filters have to pass.\n")

print("Now the cleanup, which uses its own defaults (every file, any size) — `dry_run=True`\n"
      "is what you run at 3am before you trust it:\n")
print("```python")
report = reference.cleanup(root, older_than_days=30, dry_run=True, now=NOW)
print("cleanup(root, older_than_days=30, dry_run=True, now=NOW)")
print(f"  files   -> {[str(p.relative_to(root)) for p in report['files']]}")
print(f"  bytes   -> {report['bytes']:,}")
print(f"  deleted -> {report['deleted']}")
print("```\n")

print("Nothing has gone yet:\n")
print("```python")
print(listing(root))
print("```\n")

print("The same call with `dry_run=False`:\n")
print("```python")
report = reference.cleanup(root, older_than_days=30, dry_run=False, now=NOW)
print("cleanup(root, older_than_days=30, dry_run=False, now=NOW)")
print(f"  files   -> {[str(p.relative_to(root)) for p in report['files']]}")
print(f"  bytes   -> {report['bytes']:,}")
print(f"  deleted -> {report['deleted']}")
print()
print("what's left on disk:")
print(listing(root))
print("```\n")

print("Reading that: identical report, one field different. The `deleted` flag is what keeps\n"
      "the log line honest — \"would delete 402,000 bytes\" and \"deleted 402,000 bytes\" are very\n"
      "different sentences, and the caller can tell which happened without guessing.\n")

print("Rotation is the other half, by count rather than age — `rotate(root, 'app.log.*', keep=2)`:\n")
print("```python")
removed = reference.rotate(root, "app.log.*", keep=2)
print(f"removed -> {sorted(str(p.relative_to(root)) for p in removed)}")
print(f"left    -> {listing(root)}")
print("```\n")

print("Reading that: newest two kept, the rest gone, ordered by mtime and never by name —\n"
      "sorting `app.log.10` by name would put it before `app.log.9` and rotate the wrong file.\n")

# ---------------------------------------------------------------------------

BACKUPS = [
    "db-2026-09-17.sql.gz",   # today
    "db-2026-09-16.sql.gz",
    "db-2026-09-15.sql.gz",
    "db-2026-09-14.sql.gz",
    "db-2026-09-13.sql.gz",   # Sunday
    "db-2026-09-12.sql.gz",
    "db-2026-09-11.sql.gz",
    "db-2026-09-10.sql.gz",
    "db-2026-09-06.sql.gz",   # Sunday
    "db-2026-09-01.sql.gz",   # 1st of the month
    "db-2026-08-30.sql.gz",   # Sunday
    "db-2026-08-23.sql.gz",   # Sunday
    "db-2026-08-16.sql.gz",   # Sunday
    "db-2026-08-01.sql.gz",   # 1st of the month
    "db-2026-07-01.sql.gz",   # 1st of the month
    "db-2026-07-15.sql.gz",
    "db-2026-09-18.sql.gz",   # dated tomorrow: clock skew
    "db-2026-02-30.sql.gz",   # right shape, impossible date
    "db-2026-09-14.sql.gz.tmp",   # partial upload
    "notes.txt",                  # not ours at all
]

TODAY = date(2026, 9, 17)

print("## The variant: grandfather-father-son backup retention\n")
print("Input, a backup bucket listing on 2026-09-17 (a Thursday). Keep the last 7 daily, the\n"
      "last 4 Sunday and the last 6 first-of-month backups:\n")
print("```text")
for name in BACKUPS:
    print(name)
print("```\n")

delete = variant_reference.backups_to_delete(BACKUPS, TODAY, daily=7, weekly=4, monthly=6)
keep = [n for n in sorted(BACKUPS) if n not in delete]

print("`backups_to_delete(filenames, today=date(2026, 9, 17), daily=7, weekly=4, monthly=6)`:\n")
print("```python")
for name in delete:
    print(f"delete  {name}")
print("```\n")

print("Everything it left alone:\n")
print("```python")
for name in keep:
    print(f"keep    {name}")
print("```\n")

print("Reading that: 16 real backups, 3 deleted. Each survivor is claimed by at least one rule.\n"
      "09-17 back to 09-11 are the last 7 daily. 09-13, 09-06, 08-30 and 08-23 are the last 4\n"
      "Sundays. 09-01, 08-01 and 07-01 are first-of-month. The three that go are the ones no\n"
      "rule wants: 09-10 has just dropped out of the daily window, 08-16 is the *fifth* Sunday\n"
      "back, and 07-15 is an ordinary Wednesday in July.\n"
      "\n"
      "Note what 'last 4 Sundays' means here: the 4 most recent Sunday backups that EXIST, not\n"
      "the last 4 calendar weeks. If the backup job dies for a month, a calendar window would\n"
      "quietly delete everything, which is precisely when you need the old copies.\n"
      "\n"
      "The four files that aren't ours are never touched, and they're the real safety story:\n"
      "`notes.txt` and the `.tmp` partial upload don't match the pattern, `db-2026-02-30` has\n"
      "the right shape but isn't a real date, and `db-2026-09-18` is dated tomorrow — clock\n"
      "skew is not a reason to destroy a backup. Retention code should fail towards keeping\n"
      "too much, never towards deleting something it didn't understand.")
