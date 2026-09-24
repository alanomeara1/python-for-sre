"""Run the drill 02 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
no wall-clock times, no randomness, no temp paths in the output.

Two deliberate substitutions, both marked where they happen:
  - shutil.disk_usage is replaced with fixed figures, so percentages never move.
  - the log timestamp is masked, because asctime is wall-clock by definition.
"""

import contextlib
import io
import json
import logging
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

# argparse takes its program name from sys.argv[0], so set it once for readable usage text.
sys.argv[0] = "check_disk"

GIB = 1024 ** 3
LOG_TIMESTAMP_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}", re.MULTILINE)


def usage_at(percent: float) -> SimpleNamespace:
    """A stand-in for shutil.disk_usage: 100 GiB total, filled to `percent`."""
    total = 100 * GIB
    used = int(total * percent / 100)
    return SimpleNamespace(total=total, used=used, free=total - used)


@contextlib.contextmanager
def disk_usage_returning(fake):
    # The reference calls shutil.disk_usage by attribute lookup precisely so it can be
    # swapped like this. fake is either a value to return or a callable that raises.
    real = reference.shutil.disk_usage
    reference.shutil.disk_usage = fake if callable(fake) else (lambda path: fake)
    try:
        yield
    finally:
        reference.shutil.disk_usage = real


def run(argv, fake_usage=None, module=reference, **kwargs):
    """Call main(), capturing the status line, the stderr logs and the exit code."""
    out, err = io.StringIO(), io.StringIO()
    context = disk_usage_returning(fake_usage) if fake_usage is not None else contextlib.nullcontext()
    with context, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = module.main(argv, **kwargs)
        except SystemExit as exc:               # parser.error() exits rather than returning
            code = exc.code
    return out.getvalue().strip(), LOG_TIMESTAMP_RE.sub("2026-09-17 10:15:32,000", err.getvalue()), code


print("## The main problem: a disk check the monitoring agent can read\n")

print("Four disks, one command. The percentages come from a stand-in for `shutil.disk_usage`\n"
      "(100 GiB total, filled to a fixed level), so the numbers here never move:\n")

print("```console")
for index, (percent, argv) in enumerate([
    (42.0, ["--path", "/"]),
    (85.0, ["--path", "/var"]),
    (95.0, ["--path", "/var/lib/docker"]),
    (90.0, ["--path", "/srv", "--warn", "70", "--crit", "90"]),
]):
    line, _, code = run(argv, usage_at(percent))
    if index:
        print()                                  # blank line between runs, but not a trailing one
    print(f"$ check_disk {' '.join(argv)}")
    print(line)
    print(f"$ echo $?\n{code}")
print("```")

print("Reading that: the text is for a human, the **exit code is the API**. 0 OK, 1 WARNING,\n"
      "2 CRITICAL. The last line is the boundary case: at exactly `--crit` it pages, because\n"
      "`evaluate` uses `>=` rather than `>`. An on-call engineer who sees CRITICAL on\n"
      "/var/lib/docker goes looking for image layers, not for a disk to resize.\n")

print("### When the check itself fails\n")

print("A missing mount point is not OK, and it is not CRITICAL either. It is UNKNOWN (3),\n"
      "which tells the agent \"I have no opinion\" rather than inventing one:\n")


def explode(path):
    raise OSError(2, "No such file or directory")


print("```console")
line, _, code = run(["--path", "/mnt/detached"], explode)
print("$ check_disk --path /mnt/detached")
print(line)
print(f"$ echo $?\n{code}")
print("```\n")

print("And a nonsensical threshold pair is rejected before anything is measured. `parser.error`\n"
      "writes usage to **stderr** and exits 2:\n")

print("```console")
_, err, code = run(["--warn", "95", "--crit", "90"])
print("$ check_disk --warn 95 --crit 90")
print(err.rstrip())
print(f"$ echo $?\n{code}")
print("```\n")

print("Reading that: exit 2 here means CRITICAL to a monitoring agent, which is a wart worth\n"
      "knowing. A misconfigured check pages someone, rather than passing silently.\n")

print("### Where the logging goes\n")

print("`--verbose` adds debug logging, and all of it goes to stderr so the single status line\n"
      "on stdout stays parseable. The timestamp below is masked; everything else is real:\n")

# basicConfig is a no-op once the root logger has handlers, so clear them to show the
# verbose path. That once-per-process behaviour is itself worth knowing.
logging.root.handlers.clear()

print("```console")
line, err, code = run(["--path", "/var", "--verbose"], usage_at(85.0))
print("$ check_disk --path /var --verbose")
print("# stderr:")
print(err.rstrip())
print("# stdout:")
print(line)
print("```\n")

print("Reading that: pipe stdout to the agent and stderr to a log file and each gets exactly\n"
      "what it needs. Had the debug line gone to stdout, the agent would fail to parse it.\n")

print("## The variant: certificate expiry across an inventory\n")

sys.argv[0] = "check_certs"

INVENTORY = {
    "api.example.com": "2027-03-01T00:00:00+00:00",
    "legacy.example.com": "2026-10-05T00:00:00+00:00",
    "vpn.example.com": "2026-09-20T00:00:00+00:00",
    "old.example.com": "2026-09-16T00:00:00+00:00",
}
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

print("Input, `certs.json` (the clock is pinned to 2026-09-17 12:00 UTC, so these never drift):\n")
print("```json")
print(json.dumps(INVENTORY, indent=2))
print("```\n")

with tempfile.TemporaryDirectory() as tmp:
    inventory_path = Path(tmp) / "certs.json"
    inventory_path.write_text(json.dumps(INVENTORY))

    print("```console")
    line, _, code = run([str(inventory_path)], module=variant_reference, now=NOW)
    print("$ check_certs certs.json")
    print(line)
    print(f"$ echo $?\n{code}")
    print("```\n")

    print("Reading that: soonest expiry first, and one exit code for the whole inventory — the\n"
          "worst host wins, because the codes ascend by severity. old.example.com is already\n"
          "two days gone and shows a negative count rather than being skipped, which is what\n"
          "you want: an expired certificate is the loudest case, not an absent one.\n")

    print("An unreadable inventory is UNKNOWN too, never OK:\n")

    broken = Path(tmp) / "broken.json"
    broken.write_text("{ not json at all")

    print("```console")
    line, _, code = run([str(broken)], module=variant_reference, now=NOW)
    print("$ check_certs broken.json")
    print(line)
    print(f"$ echo $?\n{code}")
    print("```\n")

print("Reading that: no data means no opinion. Reporting OK because the file failed to parse\n"
      "is how an expiry goes unnoticed until a customer finds it.")
