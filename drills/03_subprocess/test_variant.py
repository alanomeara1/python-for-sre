import os
import subprocess

import pytest

# Isolate the test repo from whatever is in the user's ~/.gitconfig (signing, hooks, templates).
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def sh_git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=GIT_ENV).stdout.strip()


def commit(repo, name, message):
    (repo / name).write_text(message)
    sh_git(repo, "add", name)
    sh_git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    sh_git(tmp_path, "init", "-q", "-b", "main")
    sh_git(tmp_path, "config", "user.email", "drill@example.com")
    sh_git(tmp_path, "config", "user.name", "Drill")
    commit(tmp_path, "a.txt", "initial commit")
    sh_git(tmp_path, "tag", "v1.0.0")
    return tmp_path


def test_git_returns_stripped_stdout(variant, repo):
    assert variant.git(repo, "rev-parse", "--is-inside-work-tree") == "true"


def test_current_branch(variant, repo):
    assert variant.current_branch(repo) == "main"
    sh_git(repo, "checkout", "-q", "-b", "release/2026-09")
    assert variant.current_branch(repo) == "release/2026-09"


def test_short_sha_matches_head(variant, repo):
    sha = variant.short_sha(repo)
    assert len(sha) >= 7
    assert sh_git(repo, "rev-parse", "HEAD").startswith(sha)


def test_is_dirty(variant, repo):
    assert variant.is_dirty(repo) is False
    (repo / "untracked.txt").write_text("x")
    assert variant.is_dirty(repo) is True


def test_is_dirty_modified_tracked_file(variant, repo):
    (repo / "a.txt").write_text("changed")
    assert variant.is_dirty(repo) is True


def test_commits_since_tag_newest_first(variant, repo):
    assert variant.commits_since(repo, "v1.0.0") == []
    commit(repo, "b.txt", "add feature b")
    commit(repo, "c.txt", "fix bug c")
    assert variant.commits_since(repo, "v1.0.0") == ["fix bug c", "add feature b"]


def test_unknown_tag_raises_git_error_with_stderr(variant, repo):
    with pytest.raises(variant.GitError) as exc:
        variant.commits_since(repo, "v9.9.9")
    assert exc.value.returncode != 0
    assert exc.value.stderr
    assert exc.value.stderr in str(exc.value)
    assert exc.value.cmd[:3] == ["git", "-C", str(repo)]


def test_not_a_repo_raises_git_error(variant, tmp_path):
    with pytest.raises(variant.GitError) as exc:
        variant.current_branch(tmp_path)
    assert "not a git repository" in str(exc.value).lower()
