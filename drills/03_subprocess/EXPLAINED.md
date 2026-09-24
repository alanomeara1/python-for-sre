# 03 · Explained: how and why, line by line

Read this in the Study step, and come back whenever you're stuck. `reference.py` shows you *what* to
write. This file is *why* it's written that way, so you can rebuild it instead of fishing for a memory.

---

## The mental model

Two halves that meet in the middle:

```
CommandResult + run_command(cmd, timeout)   run something outside Python, survive every way it can fail
parse_df(output)                            turn its text back into data
filesystems_over(output, threshold)         apply the policy
```

**Why a result object rather than returning the raw `CompletedProcess`?** Because you're adding facts
the standard library doesn't carry: how long it took, and whether it timed out. Wrapping it also means
the *caller* never has to know about `subprocess` exceptions.

**Memory hook: run it, parse it, judge it.**

The deeper idea: **the outside world fails in more ways than your code does.** A command can exit
non-zero, hang forever, or not exist at all. Three failure modes, three handled paths.

---

## Chunk 1: `CommandResult`

```python
@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out
```

- **`@dataclass` writes `__init__`, `__repr__` and `__eq__` for you.** The alternative, a 5-tuple,
  forces every caller to remember that position 2 is stderr; a dict gives you typos instead of errors.
  The `repr` alone pays for it when something fails at 3am.
- **Fields with no default come first.** `timed_out: bool = False` has to be last, because Python
  won't allow a non-default field after a defaulted one.
- **`ok` is a `@property`, not a stored field.** It's *derived*: computing it on demand means it can
  never disagree with `returncode`. Store it and someone will set one without the other.
- **Why `timed_out` at all**, when `returncode == 124` already says so? Because 124 is our convention,
  not a fact. A command could genuinely exit 124 on its own. The boolean is unambiguous.

---

## Chunk 2: `run_command`

```python
def run_command(cmd: list[str], timeout: float) -> CommandResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
```

**This is the line to have in your fingers.** Every argument is load-bearing:

| Argument | Why |
|---|---|
| `cmd` as a **list** | no shell is involved, so `"$HOME; echo pwned"` is just an argument, not a command. `shell=True` with a string is how injection bugs happen, and `test_run_command_does_not_use_a_shell` proves the list form is inert |
| `capture_output=True` | shorthand for `stdout=PIPE, stderr=PIPE`. Without it, the child writes straight to your terminal and you get nothing back |
| `text=True` | decode to `str` instead of `bytes`, so you can `.splitlines()` without `.decode()` everywhere |
| `timeout=timeout` | **the one people forget.** A hung NFS mount makes `df` block forever; a cron job without a timeout piles up copies of itself until the box dies |
| no `check=True` | `check=True` raises on a non-zero exit. Here we want to *report* failure, not crash. In a deploy script, where any failure must stop everything, you'd want the opposite |

- **`time.monotonic()`, not `time.time()`.** Monotonic only ever moves forward at a steady rate. Wall
  clocks jump when NTP corrects them or DST changes, and a jump mid-command gives you a negative
  duration. Rule: wall clock for *when*, monotonic for *how long*.

```python
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout.decode(errors="replace") if exc.stdout else ""
        return CommandResult(124, partial, f"timed out after {timeout}s",
                             time.monotonic() - start, timed_out=True)
```

- **124 mirrors GNU `timeout`**, so your script's exit codes mean the same thing as everyone else's.
- **The wart:** whatever the child printed before the timeout does **not** go through text-mode
  decoding, so `exc.stdout` comes back as bytes (or `None` if nothing was written), even though you
  passed `text=True`. Hence the `.decode(errors="replace") if ... else ""`. Not knowing this is how you
  get `AttributeError: 'bytes' object has no attribute 'splitlines'` in production only.
- **`subprocess.run` kills the child on timeout, but not its grandchildren.** If the command was a
  shell script that spawned things, they can survive. Say this aloud; the real fix is process groups.

```python
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc), time.monotonic() - start)
```

- **127 is the shell's "command not found".** Reusing it means `ok` is `False` and the code is
  recognisable. The exception message contains the binary name, which is what you need to debug it.
- **Why a separate clause:** without it, a typo in a tool name raises a bare `FileNotFoundError` that
  looks like a *file* problem, not a *binary missing* problem.

```python
    return CommandResult(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)
```

Success path last, unindented, after the exceptions are dealt with.

**How to rebuild it:** write the happy path first, then ask "what if it's slow?", "what if it isn't
there?". Each answer is one `except`.

---

## Chunk 3: `DF_RE` and `parse_df`

```python
DF_RE = re.compile(
    r"^(?P<filesystem>.+?)\s+(?P<size>\d+)\s+(?P<used>\d+)\s+(?P<available>\d+)\s+"
    r"(?P<capacity>\d+%|-)\s+(?P<mount>.+)$"
)
```

The whole reason this is a regex and not `line.split()`:

```
/dev/sda1         10255636   9230072    512000      95% /
map auto_home            0         0         0     100% /System/Volumes/Data/home     <- space in the name
/dev/sdb1        103081248  61848748  36000000      64% /mnt/my data                  <- space in the mount
```

`split()` would give `map` and `auto_home` as separate fields and shift every column after it.

| Piece | Why |
|---|---|
| `^ ... $` | anchor both ends so a partial match can't quietly succeed |
| `(?P<filesystem>.+?)` **lazy** | `.+?` takes as little as possible, so it stops as soon as the numeric columns can match. Greedy `.+` would swallow the numbers too and the match would fail |
| `\s+` between columns | one or more spaces: `df` pads its columns to different widths |
| `(?P<size>\d+)` ×3 | digits only. This is also what rejects the header row, where the columns are words |
| `(?P<capacity>\d+%\|-)` | `95%`, or `-` on a pseudo filesystem with no meaningful capacity |
| `(?P<mount>.+)$` **greedy** | takes the whole rest of the line, spaces included |

**The lazy/greedy pairing is the lesson:** lazy at the start so the anchors in the middle can find
their place, greedy at the end to take everything left.

```python
def parse_df(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        match = DF_RE.match(line)
        if not match:
            continue
```

- **No special-casing the header.** It simply doesn't match, because `1024-blocks` isn't digits. Rules
  that fall out of the pattern beat rules you maintain, like `lines[1:]`, which breaks the moment
  someone pipes you output with no header.
- **Blank lines also just don't match.** `test_parse_df_empty` covers the empty-string case.

```python
        capacity = match["capacity"]
        rows.append({
            "filesystem": match["filesystem"],
            "size_kb": int(match["size"]),
            ...
            "use_percent": 0 if capacity == "-" else int(capacity.rstrip("%")),
```

- **`match["capacity"]`** is shorthand for `match.group("capacity")`.
- **Convert at the edge**, exactly like drill 01: ints in the dict, so no caller ever compares strings.
- **`.rstrip("%")` then `int()`.** `int("95%")` raises. The `-` case becomes 0, which combined with the
  `size_kb > 0` filter below keeps pseudo filesystems out of your alerts.
- **Key names carry the unit** (`size_kb`, not `size`). Units in names prevent the class of bug where
  someone compares kilobytes to bytes.

---

## Chunk 4: `filesystems_over`

```python
def filesystems_over(df_output: str, threshold_percent: int) -> list[dict]:
    full = [fs for fs in parse_df(df_output)
            if fs["size_kb"] > 0 and fs["use_percent"] >= threshold_percent]
    return sorted(full, key=lambda fs: fs["use_percent"], reverse=True)
```

- **`size_kb > 0` drops pseudo filesystems.** `map auto_home` and docker overlays report 0 blocks and
  100% (or `-`). Without this filter your disk alert fires forever and everyone stops reading it.
  This is the difference between a check that works and a check that gets muted.
- **`>=` is inclusive**, matching the disk check in drill 02: at exactly the threshold, you want to know.
  `test_filesystems_over_threshold_is_inclusive` pins it.
- **`sorted(..., reverse=True)`** puts the worst first, which is the order a human wants to read.
  Python's sort is stable, so filesystems on the same percentage keep their `df` order.
- **Returns dicts, not formatted strings.** Presentation belongs to the caller; the `__main__` block
  does the formatting.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_run_command_captures_text_output` | missing `capture_output=True` or `text=True`, or `duration` isn't a positive float (did you use `time.monotonic()`?) |
| `test_run_command_nonzero_exit_does_not_raise` | you passed `check=True`, so a failing command raises instead of reporting |
| `test_run_command_timeout` | no `timeout=`, or you didn't catch `TimeoutExpired`, or you returned a code other than 124 / forgot `timed_out=True` |
| `test_run_command_missing_binary` | no `except FileNotFoundError`, or `stderr` doesn't contain the binary name |
| `test_run_command_does_not_use_a_shell` | you used `shell=True` or joined the list into a string |
| `test_parse_df_rows_types_and_spaces` | greedy `.+` on the filesystem column, `split()` instead of a regex, values left as strings, or `-` not mapped to 0 |
| `test_parse_df_empty` | you indexed `lines[1:]` to skip a header that isn't there |
| `test_filesystems_over_filters_sorts_and_skips_pseudo` | missing the `size_kb > 0` filter, or sorted ascending |
| `test_filesystems_over_threshold_is_inclusive` | `>` instead of `>=` |

---

## The variant: what actually changes

Git helpers for a deploy script. Same `subprocess.run`, opposite error philosophy:

1. **It raises instead of reporting.** `run_command` never raises because a monitoring check wants to
   describe every outcome. A deploy script wants to *stop*: if `git` fails, continuing would deploy
   the wrong thing. Same tool, different contract, and knowing which you want is the interesting part.
2. **A custom exception that carries structure.** `GitError` holds `cmd`, `returncode` and `stderr` as
   attributes, not just a formatted string, so a caller can log the fields or decide based on the code.
   `super().__init__(...)` still builds a readable message for the traceback.
3. **`git -C <repo>` instead of `os.chdir(repo)`.** `chdir` mutates global process state: every thread
   and every later call sees it, and forgetting to change back leaves a landmine. Passing the directory
   to the tool keeps the change local to that one call.
4. **One thin wrapper, several tiny functions.** All the policy (check the code, strip the output) lives
   in `git()`; `current_branch`, `short_sha`, `is_dirty` and `commits_since` are one line each. That's
   the shape to reach for when you're about to write the same `subprocess.run` four times.
5. **Machine-readable output on purpose.** `--porcelain` is guaranteed stable across git versions, so
   empty output means clean. `--format=%s` gives just the subject lines, newest first. Never parse the
   human-facing output of a tool that has a script-facing mode.

One thing worth noticing rather than copying: `commits_since` ends with
`output.splitlines() if output else []`. `"".splitlines()` is already `[]`, so the guard is redundant.
Harmless, and arguably clearer about intent, but don't learn it as a required idiom.
