# 02 · Variant: TLS certificate expiry check

Same skeleton (parser, `main(argv) -> int`, worst-status exit code), different input. Here the data
comes from a JSON file and time is injected.

## The task

> We keep an inventory of certificate expiry dates. Write a check that reads it and reports each host
> with days left, soonest first, and exits with the worst status across all hosts.
> Default: warning inside 30 days, critical inside 7. An expired cert is critical.

`inventory.json`:

```json
{
  "api.example.com": "2026-10-01T00:00:00+00:00",
  "db.internal": "2026-09-20T12:00:00+00:00"
}
```

```
$ check_certs.py inventory.json
CRITICAL db.internal 3 days left
WARNING api.example.com 14 days left
$ echo $?
2
```

## Contract

```python
OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
NAMES = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}

def build_parser() -> argparse.ArgumentParser
    # positional: inventory (path)   --warn-days (int, default 30)   --crit-days (int, default 7)

def days_left(expiry: datetime, now: datetime) -> int
    # whole days, rounded DOWN: (expiry - now).days. Negative once expired.

def status_for(days: int, warn_days: int, crit_days: int) -> int
    # CRITICAL if days <= crit_days, WARNING if days <= warn_days, else OK

def main(argv: list[str] | None = None, now: datetime | None = None) -> int
    # now defaults to datetime.now(timezone.utc)
    # crit_days >= warn_days            -> parser.error(...)
    # file missing or not valid JSON    -> print "UNKNOWN - cannot read inventory: <error>", return 3
    # prints "<NAME> <host> <days> days left" per host, sorted by days left, then host name
    # returns the worst (highest) code; an empty inventory returns 0
```

## Say this out loud

- "`now` is a parameter so the check is deterministic in tests. Otherwise the test breaks next month."
- "Exit with the worst status: one critical cert makes the whole check critical."
- "I sort soonest-first because that's the order a human should act in."
- "Timezones: I require aware datetimes. Subtracting naive from aware raises `TypeError`, and silently
  assuming local time is how you get an outage at midnight UTC."
- Extension: "In production I'd read the real cert: `ssl.create_default_context()` + `socket.create_connection`
  + `getpeercert()['notAfter']`. The inventory approach is what you do when you can't reach the hosts."
