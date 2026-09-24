"""Run external commands safely, and find full filesystems from df output.

Run it, parse it, judge it. The outside world fails in three ways here: non-zero exit,
hanging forever, or the binary not existing. Reasoning in EXPLAINED.md.
"""

import re
import subprocess
import time
from dataclasses import dataclass


@dataclass
class CommandResult:
    # A dataclass, not a 5-tuple: callers read fields by name, and the free __repr__ is
    # what you actually want in a log at 3am. Defaulted fields must come last.
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        # Derived, not stored, so it can never drift out of step with returncode.
        return self.returncode == 0 and not self.timed_out


def run_command(cmd: list[str], timeout: float) -> CommandResult:
    start = time.monotonic()                 # monotonic: immune to NTP/clock jumps
    try:
        # cmd is a LIST and shell=False (the default), so "x; rm -rf /" is just an argument.
        # capture_output pipes both streams; text decodes them to str.
        # No check=True: this reports failures rather than raising, because a monitoring
        # check wants to describe every outcome. A deploy script would want the opposite.
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # exc.stdout is bytes or None even with text=True, a well-known wart.
        # Partial output never goes through text-mode decoding, so handle both shapes.
        partial = exc.stdout.decode(errors="replace") if exc.stdout else ""
        # 124 is what GNU `timeout` returns, so our codes mean what everyone expects.
        # (run() kills the child, but not grandchildren a shell script may have spawned.)
        return CommandResult(124, partial, f"timed out after {timeout}s",
                             time.monotonic() - start, timed_out=True)
    except FileNotFoundError as exc:
        # 127 is the shell's "command not found". Without this clause a typo'd binary name
        # surfaces as a confusing file error instead of a missing-tool error.
        return CommandResult(127, "", str(exc), time.monotonic() - start)

    return CommandResult(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)


# Anchor on the five numeric-ish columns; the lazy .+? lets the device name contain spaces,
# and the final .+ lets the mount point contain spaces.
# Lazy at the start so the anchors in the middle can find their place, greedy at the end to
# take everything that's left. line.split() would break on "map auto_home" and "/mnt/my data".
# The header row needs no special case: "1024-blocks" isn't \d+, so it simply doesn't match.
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
            # Convert at the edge, and put the unit in the key so nobody compares KB to bytes.
            "filesystem": match["filesystem"],
            "size_kb": int(match["size"]),
            "used_kb": int(match["used"]),
            "available_kb": int(match["available"]),
            # int("95%") raises, so strip the sign; "-" (no meaningful capacity) becomes 0.
            "use_percent": 0 if capacity == "-" else int(capacity.rstrip("%")),
            "mount": match["mount"],
        })
    return rows


def filesystems_over(df_output: str, threshold_percent: int) -> list[dict]:
    # size_kb > 0 drops pseudo filesystems (automount maps, docker overlays). They report
    # 100% or "-" forever, and alerting on them is how a disk check gets muted.
    # >= is inclusive: at exactly the threshold you still want to know.
    full = [fs for fs in parse_df(df_output)
            if fs["size_kb"] > 0 and fs["use_percent"] >= threshold_percent]
    # Worst first, which is the order a human reads. Python's sort is stable, so ties keep
    # their original df order. Dicts out, not formatted strings: presentation is the caller's job.
    return sorted(full, key=lambda fs: fs["use_percent"], reverse=True)


if __name__ == "__main__":
    result = run_command(["df", "-P", "-k"], timeout=10)
    if not result.ok:
        raise SystemExit(f"df failed ({result.returncode}): {result.stderr}")
    for fs in filesystems_over(result.stdout, 80):
        print(f"{fs['use_percent']:>3}% {fs['mount']}")
