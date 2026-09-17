"""Run external commands safely, and find full filesystems from df output."""

import re
import subprocess
import time
from dataclasses import dataclass


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


def run_command(cmd: list[str], timeout: float) -> CommandResult:
    start = time.monotonic()                 # monotonic: immune to NTP/clock jumps
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # exc.stdout is bytes or None even with text=True, a well-known wart.
        partial = exc.stdout.decode(errors="replace") if exc.stdout else ""
        return CommandResult(124, partial, f"timed out after {timeout}s",
                             time.monotonic() - start, timed_out=True)
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc), time.monotonic() - start)

    return CommandResult(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)


# Anchor on the five numeric-ish columns; the lazy .+? lets the device name contain spaces,
# and the final .+ lets the mount point contain spaces.
DF_RE = re.compile(
    r"^(?P<filesystem>.+?)\s+(?P<size>\d+)\s+(?P<used>\d+)\s+(?P<available>\d+)\s+"
    r"(?P<capacity>\d+%|-)\s+(?P<mount>.+)$"
)


def parse_df(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        match = DF_RE.match(line)
        if not match:                        # header and blank lines don't match
            continue
        capacity = match["capacity"]
        rows.append({
            "filesystem": match["filesystem"],
            "size_kb": int(match["size"]),
            "used_kb": int(match["used"]),
            "available_kb": int(match["available"]),
            "use_percent": 0 if capacity == "-" else int(capacity.rstrip("%")),
            "mount": match["mount"],
        })
    return rows


def filesystems_over(df_output: str, threshold_percent: int) -> list[dict]:
    full = [fs for fs in parse_df(df_output)
            if fs["size_kb"] > 0 and fs["use_percent"] >= threshold_percent]
    return sorted(full, key=lambda fs: fs["use_percent"], reverse=True)


if __name__ == "__main__":
    result = run_command(["df", "-P", "-k"], timeout=10)
    if not result.ok:
        raise SystemExit(f"df failed ({result.returncode}): {result.stderr}")
    for fs in filesystems_over(result.stdout, 80):
        print(f"{fs['use_percent']:>3}% {fs['mount']}")
