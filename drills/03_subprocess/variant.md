# 03 · Variant: git helpers for a deploy script

Same `subprocess.run` line, different posture. In a deploy script, a failed command must **stop**
things, so failures become a custom exception that carries stderr.

## The task

> Our deploy script needs to know what it's deploying: current branch, short commit SHA, whether the
> working tree is dirty (refuse to deploy if so), and the commit subjects since the last release tag
> for the changelog. If git fails, raise an error that tells me what git said.

## Contract

```python
class GitError(Exception):
    # attributes: cmd (list[str]), returncode (int), stderr (str)
    # str(err) includes the stderr text

def git(repo: str | Path, *args: str) -> str
    # runs ["git", "-C", str(repo), *args]; returns stdout stripped; raises GitError on non-zero exit

def current_branch(repo) -> str              # git rev-parse --abbrev-ref HEAD
def short_sha(repo) -> str                   # git rev-parse --short HEAD
def is_dirty(repo) -> bool                   # any output from git status --porcelain (untracked counts)
def commits_since(repo, tag: str) -> list[str]
    # commit subjects in <tag>..HEAD, newest first; [] when HEAD is the tag
    # unknown tag -> GitError
```

## Say this out loud

- "`git -C <repo>` instead of `os.chdir`. `chdir` changes global state for the whole process and every thread in it."
- "Plumbing flags like `--porcelain` and `--format=%s` exist so scripts get stable output. Never parse the human output."
- "The exception carries stderr, so the deploy log says *why*, not just 'exit status 128'."
- "Detached HEAD, which is normal in CI checkouts, makes `--abbrev-ref HEAD` return the literal string `HEAD`.
  In CI I'd read the branch from the CI environment variable instead."
