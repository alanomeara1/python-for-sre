"""Kubernetes manifest linter: the checks a reviewer does by eye, automated."""

from pathlib import Path

import yaml

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}


def image_tag(image: str) -> str | None:
    if "@" in image:
        return image.split("@", 1)[1]            # pinned by digest: the best case
    last_part = image.rsplit("/", 1)[-1]         # drop "registry:5000/", its colon is a port
    return last_part.split(":", 1)[1] if ":" in last_part else None


def check_container(container: dict, pod_security: dict) -> list[tuple[str, str]]:
    problems = []
    image = container.get("image", "")

    tag = image_tag(image)
    if tag is None or tag == "latest":
        problems.append(("image-tag", f"image {image!r} is not pinned to a version"))

    # `or {}` handles a key that is missing AND a key that is present but null.
    limits = (container.get("resources") or {}).get("limits") or {}
    missing = [r for r in ("cpu", "memory") if r not in limits]
    if missing:
        problems.append(("resource-limits", f"missing limits: {', '.join(missing)}"))

    if "readinessProbe" not in container:
        problems.append(("readiness-probe", "no readinessProbe; traffic arrives before the app is ready"))

    # Container securityContext overrides the pod's, so fall back to the pod value.
    container_security = container.get("securityContext") or {}
    non_root = container_security.get("runAsNonRoot", pod_security.get("runAsNonRoot"))
    if non_root is not True:
        problems.append(("run-as-non-root", "runAsNonRoot is not true"))

    return problems


def lint_manifests(text: str) -> list[dict]:
    findings = []
    for doc in yaml.safe_load_all(text):
        if not doc or doc.get("kind") not in WORKLOAD_KINDS:
            continue                             # empty "---" docs, Services, ConfigMaps...

        name = (doc.get("metadata") or {}).get("name", "<unnamed>")
        pod_spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
        pod_security = pod_spec.get("securityContext") or {}

        for container in pod_spec.get("containers") or []:
            for rule, message in check_container(container, pod_security):
                findings.append({
                    "kind": doc["kind"],
                    "name": name,
                    "container": container.get("name", "<unnamed>"),
                    "rule": rule,
                    "message": message,
                })

    return sorted(findings, key=lambda f: (f["kind"], f["name"], f["container"], f["rule"]))


def lint_file(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return lint_manifests(f.read())


if __name__ == "__main__":
    import sys

    results = lint_file(sys.argv[1])
    for f in results:
        print(f"{f['kind']}/{f['name']} [{f['container']}] {f['rule']}: {f['message']}")
    sys.exit(1 if results else 0)
