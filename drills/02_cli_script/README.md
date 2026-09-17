# 02 · CLI script: argparse, logging, Nagios exit codes

**Why this drill:** Most SRE Python is a script someone else runs, whether from cron, a monitoring
agent or a runbook. The skeleton is always the same: parser, logging, `main()`, exit code.
If you can type that skeleton without thinking, every other script question starts two minutes ahead.

## The task, as an interviewer would say it

> Write a disk check our monitoring agent can call. It takes a path and warning/critical thresholds
> as percent used, prints one status line, and exits 0 for OK, 1 for WARNING, 2 for CRITICAL,
> the Nagios convention. Give it a `--verbose` flag for debugging.

```
$ check_disk.py --path / --warn 80 --crit 90
DISK WARNING - / 85.0% used
$ echo $?
1
```

## Contract (what the tests call)

```python
OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3

def build_parser() -> argparse.ArgumentParser
    # --path (default "/"), -w/--warn (float, default 80), -c/--crit (float, default 90), -v/--verbose

def evaluate(percent_used: float, warn: float, crit: float) -> tuple[int, str]
    # (2, "CRITICAL") if percent_used >= crit
    # (1, "WARNING")  if percent_used >= warn
    # (0, "OK")       otherwise

def main(argv: list[str] | None = None) -> int
    # warn >= crit            -> parser.error(...)   (argparse exits with code 2)
    # disk_usage raises OSError -> print "DISK UNKNOWN - <path>: <error>", return 3
    # otherwise prints "DISK <NAME> - <path> <percent:.1f>% used" and returns the code
```

Call it as `shutil.disk_usage(...)`, not `from shutil import disk_usage`. The tests patch
`shutil.disk_usage`, the same way you'd mock it in real unit tests.

## Patterns you are drilling

- `build_parser()` kept separate from `main()` so it can be tested
- `def main(argv=None) -> int:` + `parser.parse_args(argv)`, so tests can pass a list
- `if __name__ == "__main__": sys.exit(main())`. The return value becomes the process exit code.
- `logging.basicConfig(level=..., format=..., stream=sys.stderr)` with `--verbose` switching to DEBUG
- `parser.error("...")` for validation that involves two arguments
- `type=float` on arguments, so you never compare strings to numbers

## Say this out loud (what the interviewer listens for)

- "Status goes to stdout, diagnostics go to stderr. The agent parses stdout, so logs must not pollute it."
- "`main()` returns an int instead of calling `sys.exit` all over the place. That makes it testable."
- "I treat 'can't check' as UNKNOWN (3), not OK. A check that silently passes when it can't read the disk is worse than no check."
- "The thresholds use `>=`. At exactly 90% I want to be paged, not argue about boundaries."

## Traps

- argparse's own error exit code is 2, which Nagios reads as CRITICAL. Worth mentioning: a typo in the
  check's config shows up as a critical alert. Most shops accept that because it's loud.
- `logging.basicConfig` does nothing if the root logger already has handlers. Call it once, early, in `main()`.
- `usage.used / usage.total` can differ from `df` because of reserved root blocks. Mention it; don't solve it.
- Forgetting `type=float`, so `"85" >= "9"` compares strings and gives the wrong answer.
