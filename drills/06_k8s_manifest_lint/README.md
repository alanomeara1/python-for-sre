# 06 · Kubernetes manifest linter

**Why this drill:** "Write a quick check for our manifests before they merge" is a realistic
platform-team ask and a common take-home. It tests YAML handling, defensive dict access on
messy nested data, and whether you know what makes a workload production-ready. For a manager
role, the checks you pick matter as much as the code.

## The task, as an interviewer would say it

> Teams keep shipping Deployments with `:latest` images, no resource limits and no readiness
> probes. Write a linter that takes a multi-document manifest file and reports every problem,
> per container, for Deployments, StatefulSets and DaemonSets. Ignore everything else.

Rules (rule id → condition):

| rule | flag the container when |
|---|---|
| `image-tag` | image has no tag, or the tag is `latest` (a `@sha256:` digest is fine) |
| `resource-limits` | `resources.limits` is missing `cpu` or `memory` |
| `readiness-probe` | no `readinessProbe` |
| `run-as-non-root` | `runAsNonRoot` isn't `true`. Container `securityContext` overrides pod `securityContext`. |

## Contract (what the tests call)

```python
def image_tag(image: str) -> str | None
    # "nginx:1.25" -> "1.25", "nginx" -> None, "registry:5000/app" -> None,
    # "registry:5000/app:2.0" -> "2.0", "app@sha256:abc..." -> "sha256:abc..."

def lint_manifests(text: str) -> list[dict]
    # -> [{"kind": "Deployment", "name": "api", "container": "web",
    #      "rule": "image-tag", "message": "..."}, ...]
    # sorted by (kind, name, container, rule)

def lint_file(path: str | Path) -> list[dict]
```

## Patterns you are drilling

- `yaml.safe_load_all(text)`: a generator of documents. Some are `None` (empty `---` sections).
- `yaml.safe_load`, never `yaml.load`. `load` can construct arbitrary Python objects.
- `(d.get("key") or {})`: survives both a *missing* key and a key present with a *null* value.
- `rsplit("/", 1)` before looking for `:`, because a registry port also has a colon.
- Collect findings into a list of dicts, then `sorted(..., key=lambda f: (...))` once at the end.

## Say this out loud (what the interviewer listens for)

- "I use `safe_load_all`, because manifests are multi-doc and `load` is unsafe on untrusted input."
- "I report every finding rather than stopping at the first. A dev fixing a PR wants the whole list."
- "Output is sorted so it's stable in CI logs and diffable."
- "In real life I'd reach for kube-linter, conftest/OPA or Kyverno admission policies. This is the
  thirty-line version for understanding, and admission control is where enforcement really belongs."
- Extension to expect: *"make it exit non-zero in CI"* → wrap it in the drill 02 CLI skeleton, `return 1 if findings else 0`.

## Traps

- `resources:` with nothing under it parses to `None`, so `.get("resources", {}).get("limits")` blows up.
  That's why the reference uses `or {}`.
- `"registry:5000/app".split(":")` finds the port, not a tag.
- Treating a digest as untagged. Digests are the *most* pinned form.
- Pod-level `runAsNonRoot: true` with a container that sets `runAsNonRoot: false`. The container wins.
- `for doc in yaml.safe_load_all(...)` then `doc["kind"]` on a `None` doc.
