"""Kubernetes manifest linter: the checks a reviewer does by eye, automated.

Three layers: a pure string function (image_tag), the rules for one container
(check_container), and the walk over documents that labels and sorts findings
(lint_manifests). Adding a rule touches one function. Full reasoning in EXPLAINED.md.
"""

from pathlib import Path

import yaml

# A set because membership is all we do with it, and one obvious place to add "Job".
# These three own a pod template and run continuously, so "no readiness probe" and
# "no limits" are meaningful failures; a Service or ConfigMap has no containers.
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}


def image_tag(image: str) -> str | None:
    # An image reference has three places a colon can appear and only one is a tag:
    # a registry port (registry:5000/app), a digest (app@sha256:...), and the tag itself.
    if "@" in image:
        return image.split("@", 1)[1]            # pinned by digest: the best case
    # A tag can only live in the LAST path segment, so drop the rest and the port
    # colon goes with it. image.split(":")[-1] would return "5000/app" here and let
    # an unpinned image pass the lint.
    last_part = image.rsplit("/", 1)[-1]         # drop "registry:5000/", its colon is a port
    return last_part.split(":", 1)[1] if ":" in last_part else None


def check_container(container: dict, pod_security: dict) -> list[tuple[str, str]]:
    # Collect every problem rather than raising on the first: whoever is fixing the PR
    # wants the whole list in one run. (rule_id, message): the id is for machines to
    # filter and count, the message is for humans, and either can change alone.
    problems = []
    # Invalid Kubernetes, but a linter reports rather than crashes: "" lints as unpinned.
    image = container.get("image", "")

    tag = image_tag(image)
    if tag is None or tag == "latest":
        problems.append(("image-tag", f"image {image!r} is not pinned to a version"))

    # `or {}` handles a key that is missing AND a key that is present but null.
    # In YAML "resources:" with nothing under it parses to None, so .get("resources", {})
    # returns None (the key exists!) and the next .get raises AttributeError.
    limits = (container.get("resources") or {}).get("limits") or {}
    # Limits, not requests: requests decide scheduling, limits decide the blast radius.
    # One finding naming everything missing, so the dev fixes both in one go.
    missing = [r for r in ("cpu", "memory") if r not in limits]
    if missing:
        problems.append(("resource-limits", f"missing limits: {', '.join(missing)}"))

    # Without this, the Service routes to the pod the moment the container starts,
    # so every rolling deploy sprays 502s while the app is still warming up.
    if "readinessProbe" not in container:
        problems.append(("readiness-probe", "no readinessProbe; traffic arrives before the app is ready"))

    # Container securityContext overrides the pod's, so fall back to the pod value.
    container_security = container.get("securityContext") or {}
    # A default ARGUMENT, not `or`: the container may legitimately override true with
    # false, and `False or pod_true` would evaluate to True and hide the one root container.
    # .get(key, default) uses the default only when the key is truly absent.
    non_root = container_security.get("runAsNonRoot", pod_security.get("runAsNonRoot"))
    # Value can be True / False / None (unset) and only True is acceptable. `is not True`
    # also refuses a truthy string like "yes" that quoting can produce.
    if non_root is not True:
        problems.append(("run-as-non-root", "runAsNonRoot is not true"))

    return problems


def lint_manifests(text: str) -> list[dict]:
    findings = []
    # safe_load_all, never load_all: manifests are untrusted input and yaml.load can
    # construct arbitrary Python objects. _all because k8s files are multi-document,
    # and it yields lazily rather than holding every document at once.
    for doc in yaml.safe_load_all(text):
        # A stray or doubled "---" yields None; without this guard the first blank
        # section raises AttributeError, and real files are full of them.
        if not doc or doc.get("kind") not in WORKLOAD_KINDS:
            continue                             # empty "---" docs, Services, ConfigMaps...

        # A placeholder, not None: this goes into the sort key, where None won't compare.
        name = (doc.get("metadata") or {}).get("name", "<unnamed>")
        # One `or {}` per nesting step, because a half-written manifest can be missing
        # or null at any level. Report what we can, skip what we can't.
        pod_spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
        pod_security = pod_spec.get("securityContext") or {}

        for container in pod_spec.get("containers") or []:
            for rule, message in check_container(container, pod_security):
                findings.append({
                    # [] not .get(): the guard above already proved "kind" exists.
                    "kind": doc["kind"],
                    "name": name,
                    "container": container.get("name", "<unnamed>"),
                    "rule": rule,
                    "message": message,
                })

    # Sort once at the end: YAML order is arbitrary, and stable output means CI logs
    # diff cleanly and tests can assert an exact list.
    return sorted(findings, key=lambda f: (f["kind"], f["name"], f["container"], f["rule"]))


def lint_file(path: str | Path) -> list[dict]:
    # read() is fine here, unlike drill 01: YAML needs the whole document anyway and
    # manifests are kilobytes. Streaming matters when the input size is unbounded.
    with open(path, encoding="utf-8") as f:
        return lint_manifests(f.read())


if __name__ == "__main__":
    import sys

    results = lint_file(sys.argv[1])
    for f in results:
        print(f"{f['kind']}/{f['name']} [{f['container']}] {f['rule']}: {f['message']}")
    # Non-zero exit is what makes this a gate rather than decoration.
    sys.exit(1 if results else 0)
