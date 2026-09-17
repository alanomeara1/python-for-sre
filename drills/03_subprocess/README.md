# 03 · subprocess: run commands safely, parse df

**Why this drill:** Half of ops automation is "run a command, check it worked, parse what it printed".
Interviewers use it to spot people who reach for `os.system` or `shell=True`, or who never set a timeout.
Get the `subprocess.run(...)` line into your fingers.

## The task, as an interviewer would say it

> Write a helper that runs an external command and tells me the exit code, stdout, stderr, and how long
> it took, and never hangs forever. Then use it on `df -P -k`: give me every filesystem over some
> usage threshold.

```
Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/sda1         10255636   9230072    512000      95% /
map auto_home            0         0         0     100% /System/Volumes/Data/home
/dev/sdb1        103081248  61848748  36000000      64% /mnt/my data
```

## Contract (what the tests call)

```python
@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    duration: float          # seconds, measured with time.monotonic()
    timed_out: bool = False

    @property
    def ok(self) -> bool     # returncode == 0 and not timed_out

def run_command(cmd: list[str], timeout: float) -> CommandResult
    # never raises for a failing command
    # timeout            -> timed_out=True, returncode=124 (like GNU `timeout`)
    # binary not found   -> returncode=127 (like the shell), stderr=str(exception)

def parse_df(output: str) -> list[dict]
    # [{"filesystem": "/dev/sda1", "size_kb": 10255636, "used_kb": 9230072,
    #   "available_kb": 512000, "use_percent": 95, "mount": "/"}, ...]
    # skips the header and blank lines; filesystem and mount may contain spaces

def filesystems_over(df_output: str, threshold_percent: int) -> list[dict]
    # use_percent >= threshold, ignoring size_kb == 0 pseudo filesystems, highest use first
```

## Patterns you are drilling

- `subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)`: **the** line
- A list of args, never `shell=True` with a string
- `except subprocess.TimeoutExpired` and `except FileNotFoundError`
- `@dataclass` for results instead of a loose tuple
- `time.monotonic()` for durations, because wall clocks jump
- Regex with lazy `.+?` for columns that can contain spaces

## Say this out loud (what the interviewer listens for)

- "List arguments with no shell, so a filename like `x; rm -rf /` is just a filename. No injection."
- "Always a timeout. A hung NFS mount will make `df` block forever, and a cron job without a timeout piles up copies of itself."
- "I don't use `check=True` here because I want to *report* failures, not crash. In a deploy script where
  any failure should stop everything, I would."
- "`df -P` is the POSIX format, one line per filesystem, so long device names don't wrap onto a second line."

## Traps

- `TimeoutExpired.stdout` is **bytes** (or None) even with `text=True`. Decode it if you keep partial output.
- `subprocess.run` kills the child on timeout, but not grandchildren a shell script spawned.
- Splitting df lines on whitespace breaks on `map auto_home` and `/mnt/my data`.
- Zero-size pseudo filesystems report 100% and will page you forever if you don't filter them.
