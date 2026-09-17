"""git helpers for a deploy script: fail loudly, with git's own error message."""

import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"{' '.join(cmd)} failed ({returncode}): {stderr}")


def git(repo: str | Path, *args: str) -> str:
    # -C runs git in that directory without os.chdir() changing global process state.
    cmd = ["git", "-C", str(repo), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise GitError(cmd, proc.returncode, proc.stderr.strip())
    return proc.stdout.strip()


def current_branch(repo: str | Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def short_sha(repo: str | Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD")


def is_dirty(repo: str | Path) -> bool:
    # --porcelain is the stable, script-friendly format: empty output means clean.
    return git(repo, "status", "--porcelain") != ""


def commits_since(repo: str | Path, tag: str) -> list[str]:
    output = git(repo, "log", "--format=%s", f"{tag}..HEAD")
    return output.splitlines() if output else []


if __name__ == "__main__":
    if is_dirty("."):
        raise SystemExit("Refusing to deploy: working tree is dirty")
    print(f"Deploying {current_branch('.')} @ {short_sha('.')}")
