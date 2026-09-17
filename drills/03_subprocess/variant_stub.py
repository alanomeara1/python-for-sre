"""git helpers for a deploy script: fail loudly, with git's own error message.

Spec: drills/03_subprocess/variant.md
"""

import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        raise NotImplementedError


def git(repo: str | Path, *args: str) -> str:
    raise NotImplementedError


def current_branch(repo: str | Path) -> str:
    raise NotImplementedError


def short_sha(repo: str | Path) -> str:
    raise NotImplementedError


def is_dirty(repo: str | Path) -> bool:
    raise NotImplementedError


def commits_since(repo: str | Path, tag: str) -> list[str]:
    raise NotImplementedError
