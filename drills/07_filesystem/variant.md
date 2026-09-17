# 07 · Variant: grandfather-father-son backup retention

Same thinking as the main drill (decide what is safe to delete, and err towards keeping), but as
a pure function over filenames. There's no filesystem involved, so it's easy to test and hard to get subtly wrong.

## The task

> Nightly database backups land in a bucket as `db-YYYY-MM-DD.sql.gz`. Storage is costing too
> much. Keep the last 7 daily backups, the last 4 weekly (Sunday) backups and the last 6 monthly
> (1st of the month) backups. Everything else can go. Tell me which files to delete.

## Contract

```python
def backups_to_delete(filenames: Iterable[str], today: date,
                      daily: int = 7, weekly: int = 4, monthly: int = 6) -> list[str]
```

- "Last N" means the N **most recent backups that exist**, not "the last N calendar days". If
  backups silently stopped three weeks ago, you still keep the newest 7 you've got.
- A backup is kept if **any** rule keeps it (a Sunday that is also in the last 7 counts for both).
- Names that don't match `db-YYYY-MM-DD.sql.gz` exactly, or aren't real dates (`db-2026-02-30...`),
  are never returned. Don't delete what you don't understand.
- Backups dated **after** `today` (clock skew, timezone) are never deleted and don't use up a slot.
- Return value sorted ascending (oldest first).

## Say this out loud

- "Retention is a union of keep rules. I compute the keep set, then delete is everything else."
- "Most-recent-N rather than a calendar window. A calendar window deletes all your dailies
  if the backup job has been broken for a week, which is exactly when you need them."
- "Unrecognised files are left alone. The safe failure mode is using too much storage."
- "`date.fromisoformat` validates the date. My regex only checks the shape."
- "In S3 I'd prefer lifecycle rules for the simple cases. GFS usually needs code like this or tags."
