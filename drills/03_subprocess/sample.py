"""Run the drill 03 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift.
Three deliberate substitutions, each marked where it happens:
  - measured durations are masked: they are real elapsed time by definition.
  - sys.executable is displayed as `python`, so the command reads like a shell line.
  - the temp repo path is displayed as `<repo>`.

The git section pins author, committer, dates and config, so the commit sha below is
reproducible: git object ids are a hash of exactly that content.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

DURATION_RE = re.compile(r"duration=[0-9.e+-]+")


def show_cmd(cmd: list[str]) -> str:
    """The argument list as passed, with the long interpreter path shortened to `python`."""
    return repr(["python" if part == sys.executable else part for part in cmd])


def show_result(result) -> str:
    """The real dataclass repr, with the measured duration masked."""
    return DURATION_RE.sub("duration=<measured>", repr(result))


print("## The main problem: running commands that misbehave\n")

print("Four outcomes, one function. The `duration` field is masked below because it is real\n"
      "elapsed time; everything else is exactly what `run_command` returned:\n")

print("```python")
for index, (cmd, timeout, label) in enumerate([
    ([sys.executable, "-c", "print('deploy finished')"], 5, "success"),
    ([sys.executable, "-c", "import sys; sys.stderr.write('config missing\\n'); sys.exit(3)"], 5, "non-zero exit"),
    ([sys.executable, "-c", "import time; time.sleep(30)"], 0.2, "hangs, so we time it out"),
    (["kubectl-that-isnt-installed", "get", "pods"], 5, "binary not found"),
]):
    result = reference.run_command(cmd, timeout=timeout)
    if index:
        print()
    print(f"# {label}")
    print(f">>> run_command({show_cmd(cmd)}, timeout={timeout})")
    print(show_result(result))
    print(f"    .ok -> {result.ok}")
print("```")

print("Reading that: none of the four raised. The caller gets a record it can log or branch on,\n"
      "which is what a monitoring check needs. Note the borrowed exit codes: **124** for a\n"
      "timeout is what GNU `timeout` returns, **127** for a missing binary is what a shell\n"
      "returns, so existing runbooks and dashboards already know what they mean. The timeout\n"
      "case also shows why `timeout=` is not optional: without it, that call never returns.\n")

print("### Turning `df` text into data\n")

DF_OUTPUT = """\
Filesystem     1024-blocks      Used Available Capacity  Mounted on
/dev/disk1s5     488245288 421338112  52341880      89%  /
/dev/disk1s4     488245288   2097152 452341880       1%  /System/Volumes/VM
map auto_home            0         0         0     100%  /System/Volumes/Data/home
/dev/disk2s1      97656250  92773437   4882813      95%  /mnt/data volume
tmpfs                 8192      8192         0     100%  /run/lock
"""

print("Input (note the pseudo filesystem with a zero size, and the mount point with a space\n"
      "in its name, both of which break a naive `line.split()`):\n")
print("```text")
print(DF_OUTPUT.rstrip())
print("```\n")

rows = reference.parse_df(DF_OUTPUT)
print(f"`parse_df(output)` returns {len(rows)} rows, typed and unit-suffixed. The first two:\n")
print("```json")
print(json.dumps(rows[:2], indent=2))
print("```\n")

print("`filesystems_over(output, threshold)`, worst first:\n")
print("```python")
for threshold in (90, 89):
    hits = reference.filesystems_over(DF_OUTPUT, threshold)
    print(f">>> [(fs['use_percent'], fs['mount']) for fs in filesystems_over(df, {threshold})]")
    print(f"{[(fs['use_percent'], fs['mount']) for fs in hits]}")
print("```\n")

print("Reading that: the header row needed no special case, because `1024-blocks` is not a\n"
      "number and so never matched. `map auto_home` sits at 100% forever and is dropped by the\n"
      "`size_kb > 0` filter — alerting on it is how a disk check ends up muted. Dropping the\n"
      "threshold from 90 to 89 pulls `/` in, because the comparison is `>=`: at exactly the\n"
      "threshold you still want to know.\n")

print("## The variant: git facts for a deploy script\n")

# Pin everything that feeds the commit hash, so the sha below is reproducible.
# git ignores the user's global and system config when these point at /dev/null.
os.environ.update({
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "Sample Author",
    "GIT_AUTHOR_EMAIL": "sample@example.com",
    "GIT_COMMITTER_NAME": "Sample Author",
    "GIT_COMMITTER_EMAIL": "sample@example.com",
    "GIT_AUTHOR_DATE": "2026-09-17T10:00:00+0000",
    "GIT_COMMITTER_DATE": "2026-09-17T10:00:00+0000",
    "TZ": "UTC",
})


def git_quiet(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    git_quiet(repo, "init", "-b", "main")           # -b main: don't inherit init.defaultBranch

    (repo / "README.md").write_text("# payments-api\n")
    git_quiet(repo, "add", "-A")
    git_quiet(repo, "commit", "-m", "Initial import")
    git_quiet(repo, "tag", "v1.0")

    (repo / "deploy.sh").write_text("#!/bin/sh\necho deploying\n")
    git_quiet(repo, "add", "-A")
    git_quiet(repo, "commit", "-m", "Add deploy script")

    (repo / "README.md").write_text("# payments-api\n\n## Rollback\n")
    git_quiet(repo, "add", "-A")
    git_quiet(repo, "commit", "-m", "Document the rollback path")

    print("A repository with three commits and a `v1.0` tag on the first:\n")
    print("```python")
    print(f">>> current_branch(repo)     -> {variant_reference.current_branch(repo)!r}")
    print(f">>> short_sha(repo)          -> {variant_reference.short_sha(repo)!r}")
    print(f">>> is_dirty(repo)           -> {variant_reference.is_dirty(repo)}")
    print(f">>> commits_since(repo, 'v1.0')")
    print(f"{variant_reference.commits_since(repo, 'v1.0')}")
    print("```\n")

    print("Reading that: newest first, subject lines only, which is the shape a release note\n"
          "wants. The sha is stable here only because the author, committer and dates are\n"
          "pinned: a git object id is a hash of exactly that content.\n")

    print("Now touch a tracked file without committing, which is the state a deploy must refuse:\n")

    (repo / "deploy.sh").write_text("#!/bin/sh\necho deploying v2\n")

    print("```python")
    print(f">>> is_dirty(repo)           -> {variant_reference.is_dirty(repo)}")
    print("```\n")

    print("And when git itself fails, the error carries git's own words rather than a guess:\n")

    print("```python")
    try:
        variant_reference.commits_since(repo, "v9.9")
    except variant_reference.GitError as exc:
        # The repo path is a temp directory, so display it as <repo>.
        cmd = [part if part != str(repo) else "<repo>" for part in exc.cmd]
        print(f">>> commits_since(repo, 'v9.9')")
        print(f"GitError: {' '.join(cmd)} failed ({exc.returncode})")
        print(f"  stderr: {exc.stderr.splitlines()[0]}")
    print("```\n")

print("Reading that: the deploy stops, and the message names the command, the exit code and\n"
      "git's own explanation. That is the opposite contract to `run_command` above: a check\n"
      "wants to describe every outcome, a deploy wants to stop before it ships the wrong commit.")
