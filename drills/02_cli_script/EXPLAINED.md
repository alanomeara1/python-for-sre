# 02 · Explained: how and why, line by line

Read this in the Study step, and come back whenever you're stuck. `reference.py` shows you *what* to
write. This file is *why* it's written that way, so you can rebuild it instead of fishing for a memory.

---

## The mental model

Three functions, and the skeleton never changes no matter what the script does:

```
build_parser()                  describe the arguments   (no side effects, so it's testable alone)
evaluate(percent, warn, crit)   the decision             (pure: numbers in, verdict out)
main(argv=None) -> int          wire it together         (parse, validate, log, act, print, return code)
```

**Why three pieces rather than one `main()`?** Everything interesting gets testable without running the
whole program. `evaluate` is pure, so its boundaries can be checked in five lines. `build_parser` can be
asked what its defaults are. `main` is the only part that touches the outside world.

**Memory hook: parser, decision, wiring.**

The deeper idea: **a CLI script's real API is its exit code**, not its output. A monitoring agent runs
this every minute and reads one integer. Everything else is for humans.

---

## Chunk 1: Imports and the exit codes

```python
import argparse
import logging
import shutil
import sys

log = logging.getLogger("check_disk")

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
```

- **`log = logging.getLogger("check_disk")` at module level.** A *named* logger, created once. Logging to
  the root logger (`logging.info(...)`) works but gives you no way to turn this script's noise up or down
  separately from any library's. The convention in a package is `logging.getLogger(__name__)`.
- **The four constants** name the Nagios convention: 0 OK, 1 WARNING, 2 CRITICAL, 3 UNKNOWN. Writing
  `return 2` scattered through the code is how you end up with a check that exits 1 where it meant 2.
- **Why `shutil` imported as a module**, then called as `shutil.disk_usage(...)`? Because the tests
  (and real unit tests) patch the attribute on the module. `from shutil import disk_usage` copies the
  function into your namespace, and patching `shutil.disk_usage` afterwards has no effect on your copy.
  That's a genuinely useful thing to understand, not a test quirk.

**If you're stuck:** the imports fall out of the jobs. Parse arguments, log, read the disk, exit.

---

## Chunk 2: `build_parser`

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check disk usage against thresholds.")
    parser.add_argument("--path", default="/", help="mount point to check (default: /)")
    parser.add_argument("-w", "--warn", type=float, default=80.0, help="warning at this percent used")
    parser.add_argument("-c", "--crit", type=float, default=90.0, help="critical at this percent used")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    return parser
```

| Piece | Why |
|---|---|
| a function, not module-level code | building the parser at import time means you can't test it, and any import gets the side effects |
| `--path` with a default | optional arguments with sensible defaults beat positional ones for a check run by an agent |
| `-w, --warn` | both spellings register one argument; the long name becomes `args.warn` |
| `type=float` | argparse hands you **strings** otherwise, and `"85" >= "9"` is `False` because it compares text, not numbers. Silent, wrong, and a classic |
| `action="store_true"` | a flag that takes no value; `args.verbose` is `False` unless `-v` is given |
| `help=` on everything | `--help` is the script's documentation, and it costs one string |

**How to rebuild it:** ask what a person typing this command needs to vary. Where, and the two
thresholds. Then ask what they'd want while debugging: more logging.

---

## Chunk 3: `evaluate`

```python
def evaluate(percent_used: float, warn: float, crit: float) -> tuple[int, str]:
    if percent_used >= crit:
        return CRITICAL, "CRITICAL"
    if percent_used >= warn:
        return WARNING, "WARNING"
    return OK, "OK"
```

- **Most severe first.** The conditions overlap: 95% is over both thresholds. Testing `crit` first means
  the first match is the right one. Reverse the order and everything critical reports as a warning, which
  is the single most common bug in this kind of code.
- **`>=`, not `>`.** At exactly 90.0% you want the page. Boundary behaviour is the thing an interviewer
  will poke at, and `test_evaluate_levels_and_boundaries` checks 80.0, 89.9, 90.0 for exactly that reason.
- **Returning `(code, name)` together** saves a second lookup later and keeps the two in step: the name
  printed always matches the code returned.
- **It's pure.** No printing, no disk access, no globals. That's what makes it trivially testable and
  what lets you reason about it out loud.

---

## Chunk 4: `main`

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.warn >= args.crit:
        parser.error("--warn must be lower than --crit")
```

- **`argv: list[str] | None = None`** is the whole trick for testable CLIs. `parse_args(None)` falls back
  to `sys.argv[1:]`, so production behaviour is unchanged, while a test calls `main(["--path", "/data"])`
  with no process to spawn and no monkeypatching of `sys.argv`.
- **`main` returns an int, it doesn't call `sys.exit`.** A function that kills the process can't be
  tested and can't be reused. The `__main__` guard converts the return value into the exit status.
- **`parser.error(...)` for validation involving two arguments.** argparse can enforce types and choices
  per argument, but "warn must be below crit" is a relationship. `parser.error` prints usage plus the
  message **to stderr** and exits **2**. Worth voicing: Nagios reads 2 as CRITICAL, so a misconfigured
  check alerts loudly rather than passing silently. Most shops prefer that.

```python
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
```

- **`stream=sys.stderr`** is the point of the whole drill. The monitoring agent parses **stdout**, where
  your one status line lives. Logs must not land there or you corrupt the check's output.
  `test_status_line_is_the_only_stdout` runs with `-v` and asserts stdout still has exactly one line.
- **Configured after parsing, before any work**, because the verbosity comes from the arguments.
- **The trap:** `logging.basicConfig` does nothing if the root logger already has handlers. Call it once,
  early. If you call it again later with different settings, you'll wonder why nothing changed.

```python
    try:
        usage = shutil.disk_usage(args.path)
    except OSError as exc:
        print(f"DISK UNKNOWN - {args.path}: {exc}")
        return UNKNOWN
```

- **"Couldn't check" is not "OK".** A check that returns 0 when the path doesn't exist is worse than no
  check, because it manufactures confidence. UNKNOWN (3) says "I have no information".
- **Catch `OSError`, not `Exception`.** `FileNotFoundError`, `PermissionError` and friends all subclass
  `OSError`, so one clause covers the real failure modes while a genuine bug in your own code still
  crashes loudly with a traceback. `test_main_unknown_when_disk_unreadable` raises `FileNotFoundError`.
- **Still prints a status line** in the agent's expected shape, so a human reading the check output sees
  what happened rather than a bare exit code.

```python
    percent = usage.used / usage.total * 100
    log.debug("path=%s total=%d used=%d percent=%.2f", args.path, usage.total, usage.used, percent)

    code, name = evaluate(percent, args.warn, args.crit)
    print(f"DISK {name} - {args.path} {percent:.1f}% used")
    return code
```

- **`shutil.disk_usage` returns a named tuple** `(total, used, free)`, so `usage.used` reads clearly.
- **`log.debug("...%s...", value)`, not an f-string.** Logging does the formatting only if the message is
  actually emitted. With an f-string you pay the formatting cost on every call even when DEBUG is off,
  and you lose the structured arguments that log aggregators can group on. This is a real habit
  interviewers notice.
- **`{percent:.1f}`** keeps the line stable: one decimal place, always.
- **`return code`**, so the caller decides what to do with it.

Worth mentioning aloud: `used / total` can disagree with `df`, which reserves ~5% of blocks for root.
Name the discrepancy, don't try to solve it in an interview.

---

## Chunk 5: The guard

```python
if __name__ == "__main__":
    sys.exit(main())
```

`sys.exit(int)` sets the process exit status. Because `main` returns the code rather than exiting, the
whole program is importable and testable, and this one line is the only place that touches the process.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_evaluate_levels_and_boundaries` | you used `>` instead of `>=`, or checked `warn` before `crit` |
| `test_parser_defaults` | a missing `default=`, or you defaulted `--path` to something other than `/` |
| `test_parser_short_flags_and_types` | no `-w`/`-c`/`-v` short forms, or a missing `type=float` (you'll see strings) |
| `test_main_ok` | output text doesn't match exactly: it's `DISK OK - / 50.0% used` with `.1f` |
| `test_main_warning` | thresholds not applied, or `evaluate` got its arguments in the wrong order |
| `test_main_critical_checks_the_given_path` | you ignored `args.path` and hardcoded `/` |
| `test_main_rejects_warn_not_below_crit` | missing the `warn >= crit` check, or you raised something other than `parser.error` (which exits 2 and writes to stderr) |
| `test_main_unknown_when_disk_unreadable` | no `try/except OSError`, or you returned 0/2 instead of 3 |
| `test_status_line_is_the_only_stdout` | logging is going to stdout: pass `stream=sys.stderr`, and don't `print` your debug output |

---

## The variant: what actually changes

Certificate expiry from a JSON inventory. Same skeleton, five conceptual differences:

1. **An injectable clock.** `main(argv=None, now=None)` then `now = now or datetime.now(timezone.utc)`.
   Anything that reads the current time is untestable until the time can be passed in. The tests pin
   `NOW` to a fixed date and get deterministic results. This is the single most reusable idea in the drill.
2. **Input is a file, so reading it can fail in two ways.**
   `except (OSError, json.JSONDecodeError)` catches both "no such file" and "the file is not JSON", and
   both mean UNKNOWN: you have no data, so you cannot say OK.
3. **Many subjects, one exit code.** A disk check judges one thing; this judges N hosts. The answer is
   `max(...)` over the per-host codes, because the codes are ordered by severity. `default=OK` handles the
   empty inventory, since `max([])` raises `ValueError`.
   (Note the ordering only works because UNKNOWN=3 never reaches that `max`: an unreadable inventory
   returns early. Worth noticing that severity and numeric order agree only up to CRITICAL.)
4. **Sorting by tuple.** `rows` holds `(days, host, code)` and a bare `rows.sort()` compares element by
   element: soonest expiry first, ties broken by host name. Deterministic output is what makes a check
   diffable and safe to feed to other tools.
5. **The threshold direction flips.** Disk: *higher* percent is worse (`>=`). Certificates: *fewer* days
   is worse (`<=`). The shape of `status_for` is identical, the comparison is mirrored. Getting this the
   wrong way round is the mistake to expect.

One more piece of reasoning worth voicing: `days_left` uses `(expiry - now).days`, and `timedelta.days`
floors rather than rounding. Two days and 23 hours reports as 2, so the check errs toward warning you
sooner. For an expiry check, rounding down is the safe direction.
