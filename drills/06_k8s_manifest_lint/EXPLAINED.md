# 06 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

---

## The mental model

Every linter, whatever it checks, has the same three layers:

```
image_tag(image)                      a string  → a fact about it
check_container(container, security)  one unit  → a list of problems
lint_manifests(text)                  a file    → every problem, labelled and sorted
```

The outer layer walks the data and labels findings. The middle layer holds the rules. The inner
layer is a pure string function you can test on its own. Keeping the rules away from the walking
is what makes a linter easy to extend: adding a rule touches one function.

**Memory hook: tag → container → document.** Smallest thing first, then build outwards.

The data direction is the opposite: a manifest file contains documents, a document contains a pod
template, a template contains containers. You're digging down, then reporting back up.

---

## Chunk 1: What counts as a workload

```python
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}
```

**Why a set at module level:** membership testing is the only thing you do with it, and `in` on a
set is O(1). At module level it's also the one place to edit when someone asks for `Job` and
`CronJob`, rather than hunting through an `if` statement.

**Why only these three:** they're the kinds that own a pod template and run continuously, so
"no readiness probe" and "no resource limits" are meaningful failures. A `Service` or `ConfigMap`
has no containers to check.

---

## Chunk 2: `image_tag`, the fiddly string function

```python
def image_tag(image: str) -> str | None:
    if "@" in image:
        return image.split("@", 1)[1]            # pinned by digest: the best case
    last_part = image.rsplit("/", 1)[-1]         # drop "registry:5000/", its colon is a port
    return last_part.split(":", 1)[1] if ":" in last_part else None
```

**The problem it solves:** a container image reference has *three* places a colon can appear, and
only one of them is a tag.

| Image string | Colon means | Right answer |
|---|---|---|
| `nginx:1.25` | tag | `"1.25"` |
| `nginx` | — | `None` (implicitly `:latest`) |
| `registry:5000/app` | **registry port** | `None` |
| `registry:5000/team/app:2.0` | port, then tag | `"2.0"` |
| `app@sha256:abc...` | **digest** | `"sha256:abc..."` |

**Why check `@` first:** a digest pins the image to exact bytes, which is stronger than any tag.
It also short-circuits the whole colon problem, since everything after `@` is the digest.

**Why `rsplit("/", 1)[-1]`:** a tag can only live in the *last* path segment. Splitting from the
right once and taking the tail throws away the registry host and any namespace, and with it the
port colon that would otherwise fool you. `split("/")[-1]` gives the same answer; `rsplit` with a
maxsplit of 1 just stops early and says "I only care about the last separator".

**Why `split(":", 1)` and not `rsplit`:** after dropping the path, at most one colon remains, so
either works. `maxsplit=1` keeps the intent explicit.

**Rebuild it from first principles:** ask "where can a colon appear, and which one do I want?"
Answer: digest first, then throw away everything that isn't the final path segment, then whatever
follows a colon in what's left.

**The trap:** `image.split(":")[-1]` looks right and quietly returns `"5000/app"` for
`registry:5000/app`. Then `tag == "latest"` is False, and an unpinned image passes the lint.

---

## Chunk 3: `check_container`, where the rules live

```python
def check_container(container: dict, pod_security: dict) -> list[tuple[str, str]]:
    problems = []
    image = container.get("image", "")

    tag = image_tag(image)
    if tag is None or tag == "latest":
        problems.append(("image-tag", f"image {image!r} is not pinned to a version"))
```

**Why return a list instead of raising or printing:** the caller decides what to do with the
findings. A developer fixing a pull request wants the whole list at once, not the first problem,
a fix, another run, another problem. "Collect, don't abort" is the general shape of a linter.

**Why `(rule_id, message)` tuples:** the rule id is for machines (filtering, counting, ignore
lists) and the message is for humans. Splitting them means the wording can change without
breaking anyone's CI filter.

**Why `container.get("image", "")`:** a container with no image is invalid Kubernetes, but the
linter's job is to report, not to crash on malformed input. An empty string flows into
`image_tag`, returns `None`, and reports as unpinned. That's a sensible answer for garbage input.

### The resources check

```python
    # `or {}` handles a key that is missing AND a key that is present but null.
    limits = (container.get("resources") or {}).get("limits") or {}
    missing = [r for r in ("cpu", "memory") if r not in limits]
    if missing:
        problems.append(("resource-limits", f"missing limits: {', '.join(missing)}"))
```

**Why `or {}` rather than `.get("resources", {})`:** this is the single most important line in the
drill. In YAML, a key written with nothing under it parses to `None`, not to an empty dict:

```yaml
resources:          # this is None, not {}
```

`.get("resources", {})` only supplies the default when the key is *absent*. When the key is
present and null, it returns `None`, and the next `.get` raises
`AttributeError: 'NoneType' object has no attribute 'get'`. `or {}` covers both cases, because
both `None` and `{}` are falsy. The test manifest has exactly this shape on the `sidecar`
container, so you'll hit it.

**Why one finding listing both missing resources**, rather than one per resource: a developer
reads "missing limits: cpu, memory" once and fixes both. The test checks that the `api` container's
message mentions `cpu` and *not* `memory`, since only `cpu` is missing there.

**Why limits and not requests:** requests decide scheduling; limits decide the blast radius. A
container with no memory limit can consume the node and evict its neighbours. In a real linter
you'd check both, and say so.

### The readiness probe check

```python
    if "readinessProbe" not in container:
        problems.append(("readiness-probe", "no readinessProbe; traffic arrives before the app is ready"))
```

**Why `in` rather than `.get()`:** you only care whether the key exists. The probe's contents are
Kubernetes' business.

**Why it matters operationally:** without a readiness probe, the moment a pod's container starts,
the Service sends it traffic, including during a rolling deploy. Requests hit a process still
loading config or warming a connection pool, and you get a burst of 502s on every deploy.

### The runAsNonRoot check

```python
    # Container securityContext overrides the pod's, so fall back to the pod value.
    container_security = container.get("securityContext") or {}
    non_root = container_security.get("runAsNonRoot", pod_security.get("runAsNonRoot"))
    if non_root is not True:
        problems.append(("run-as-non-root", "runAsNonRoot is not true"))
```

**Why a default *argument* rather than `or`:** this is the subtle one. Kubernetes lets a container
override the pod's setting, including overriding `true` with `false`. Write it as:

```python
non_root = container_security.get("runAsNonRoot") or pod_security.get("runAsNonRoot")   # WRONG
```

and a container that explicitly sets `runAsNonRoot: false` under a pod that sets `true` comes out
as `True`, because `False or True` is `True`. You'd miss the one container actually running as
root. `dict.get(key, default)` only uses the default when the key is genuinely absent, which is
exactly the override rule. The `postgres` container in the test manifest is this case.

**Why `is not True` rather than `if not non_root`:** the value can be `True`, `False`, or `None`
for "not specified", and only `True` is acceptable. `is not True` treats missing and false alike
without pretending they're the same thing. It also refuses to accept a truthy string like
`"yes"`, which YAML can produce if someone quotes the value.

---

## Chunk 4: `lint_manifests`, walking the documents

```python
    for doc in yaml.safe_load_all(text):
        if not doc or doc.get("kind") not in WORKLOAD_KINDS:
            continue                             # empty "---" docs, Services, ConfigMaps...
```

**Why `safe_load_all` and not `load_all`:** `yaml.load` can construct arbitrary Python objects
from tags like `!!python/object/apply:os.system`. Manifests come from repositories other people
write to, so they're untrusted input. `safe_load*` builds only plain dicts, lists, strings and
numbers. Say this out loud in an interview; it's a free security point.

**Why `_all`:** Kubernetes files are conventionally multi-document, separated by `---`. It returns
a *generator*, so documents are parsed one at a time rather than all held at once.

**Why `if not doc`:** a stray `---` at the start or end of a file, or two in a row, yields `None`.
`not doc` also covers an empty document. Without this, `doc.get` raises `AttributeError` on the
first blank section, and real manifest files are full of them.

```python
        name = (doc.get("metadata") or {}).get("name", "<unnamed>")
        pod_spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
        pod_security = pod_spec.get("securityContext") or {}

        for container in pod_spec.get("containers") or []:
```

**Why the chain of `or {}`:** same reason as before, one level per nesting step. The path to a
container is `spec.template.spec.containers`, and any of those can be missing or null in a file
someone is midway through writing. The linter should report what it can and skip what it can't,
rather than crash on the first malformed document and tell the developer nothing.

**Why `or []` on containers:** a workload with no containers yields nothing to check. There's a
test for exactly this (`spec: {}` on a DaemonSet), because a crash here would be the most likely
bug.

**Why `"<unnamed>"` instead of `None`:** the name ends up in the sort key and in printed output.
A placeholder string keeps both working; `None` would break the comparison against other names.

```python
                findings.append({
                    "kind": doc["kind"], ...
```

**Why `doc["kind"]` is safe here** even though everything else uses `.get`: the guard above already
proved `kind` is in `WORKLOAD_KINDS`, so it exists. Using `[]` where you've established the key
exists is a small signal that you know the difference, rather than sprinkling `.get` everywhere.

```python
    return sorted(findings, key=lambda f: (f["kind"], f["name"], f["container"], f["rule"]))
```

**Why sort at the end rather than keep order:** YAML document order is arbitrary, and dict
iteration order follows insertion. Sorting makes the output stable, so CI logs diff cleanly and a
test can assert an exact list. The tuple key gives you the obvious reading order: kind, then
workload name, then container, then rule.

**Why one sort rather than sorting as you go:** one `O(n log n)` pass at the end on a list you've
already built is simpler and faster than maintaining order during insertion.

---

## Chunk 5: `lint_file`

```python
def lint_file(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return lint_manifests(f.read())
```

**Why `f.read()` here, when drill 01 insisted on streaming:** manifests are kilobytes, and YAML
parsing needs the whole document anyway. Streaming matters when input size is unbounded; a
manifest file isn't. Knowing *when* the rule doesn't apply is the actual skill.

**Why the split at all:** `lint_manifests` takes text, so tests pass a string with no filesystem
involved, and `lint_file` is a two-line wrapper. Same one/many/file layering as drill 01.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_image_tag` | the registry-port case (`registry:5000/app`), or you treated a `@sha256:` digest as untagged |
| `test_lint_exact_findings_sorted` | a rule fires wrongly, or the sort key isn't `(kind, name, container, rule)` |
| `test_findings_have_messages` | a message is empty, or you list all resources rather than only the missing ones |
| `test_non_workloads_and_empty_docs_ignored` | no `if not doc` guard, or you didn't filter on `kind` |
| `test_workload_without_containers_does_not_crash` | missing `or []` / `or {}` somewhere in the `spec.template.spec` chain |
| `test_daemonset_is_checked` | `WORKLOAD_KINDS` is missing a kind |
| `test_lint_file` | `lint_file` doesn't reuse `lint_manifests`, or opened the file wrongly |

`AttributeError: 'NoneType' object has no attribute 'get'` means you used `.get("x", {})` where
the key exists with a null value. Switch that link in the chain to `(d.get("x") or {})`.

---

## The variant: what actually changes

The Terraform plan guard walks machine-generated JSON instead of hand-written YAML. Four ideas
worth understanding rather than memorising:

1. **A dict keyed by tuples replaces an if-chain.**
   ```python
   ACTION_KINDS = {("create",): "create", ("delete", "create"): "replace", ...}
   ```
   Terraform reports actions as a *list*, and lists are unhashable because they're mutable, so
   they can't be dict keys. `tuple(actions)` converts to something hashable. A lookup table beats
   a chain of `if actions == [...]` because the mapping is data you can read at a glance.

2. **Both orderings of replace are dangerous.** `["delete", "create"]` is the normal replace;
   `["create", "delete"]` is `create_before_destroy`. The resource still gets destroyed, so both
   map to `"replace"`. Missing the second ordering is the bug the drill is built around.

3. **`None` means "nothing to report", not an error.** `no-op` and `read` classify to `None`, and
   the caller skips them. Same decision as `parse_line` returning `None` in drill 01.

4. **Always-present keys beat `.get()` at the call site.**
   ```python
   return {kind: counts[kind] for kind in ("create", "update", "delete", "replace")}
   ```
   A `Counter` only holds keys it has seen, so a plan with no deletions would have no `"delete"`
   key and every dashboard would need a default. Filling all four keys makes the return shape
   predictable, which matters more the further the data travels.

5. **Defend against a missing top-level key:** `plan.get("resource_changes", [])`. A plan with
   nothing to do can omit the key entirely, and that's the case you least want to crash on,
   because it's the one that runs on every quiet CI build.

The judgement call to voice: **this should fail the pipeline, not print a warning.** A guard
nobody is forced to read is decoration. Terraform's own `prevent_destroy` lifecycle rule is the
belt to this script's braces, since it stops the apply even when the plan is approved.
