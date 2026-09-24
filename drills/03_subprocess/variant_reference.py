"""git helpers for a deploy script: fail loudly, with git's own error message.

Opposite contract to run_command: a check wants to report every outcome, a deploy wants to
STOP before it ships the wrong commit. Reasoning in EXPLAINED.md.
"""

import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        # Keep the parts as attributes, not just a formatted string: a caller can log the
        # fields or branch on the code, which a flattened message makes impossible.
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        # ...and still give the traceback a readable one-line summary.
        super().__init__(f"{' '.join(cmd)} failed ({returncode}): {stderr}")


def git(repo: str | Path, *args: str) -> str:
    # -C runs git in that directory without os.chdir() changing global process state.
    # chdir leaks to every thread and every later call; passing the directory keeps it local.
    cmd = ["git", "-C", str(repo), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        # All the policy lives here, so the helpers below are one line each.
        raise GitError(cmd, proc.returncode, proc.stderr.strip())
    return proc.stdout.strip()               # git ends output with a newline; callers never want it


def current_branch(repo: str | Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def short_sha(repo: str | Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD")


def is_dirty(repo: str | Path) -> bool:
    # --porcelain is the stable, script-friendly format: empty output means clean.
    # Never parse git's human-facing output when it offers a machine-facing mode.
    return git(repo, "status", "--porcelain") != ""


def commits_since(repo: str | Path, tag: str) -> list[str]:
    # tag..HEAD is "commits reachable from HEAD but not from tag"; %s is the subject line only.
    # git log lists newest first, which is the order a release note wants.
    output = git(repo, "log", "--format=%s", f"{tag}..HEAD")
    # (The guard is belt and braces: "".splitlines() is already [].)
    return output.splitlines() if output else []


if __name__ == "__main__":
    if is_dirty("."):
        raise SystemExit("Refusing to deploy: working tree is dirty")
    print(f"Deploying {current_branch('.')} @ {short_sha('.')}")
