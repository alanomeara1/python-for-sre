"""Run the drill 06 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
no wall-clock times, no randomness, no temp paths in the output.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

MANIFESTS = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
      containers:
        - name: api
          image: registry.internal:5000/api:1.4.2
          resources:
            limits:
              cpu: "1"
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: api
spec:
  selector:
    app: api
---
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
spec:
  template:
    spec:
      containers:
        - name: worker
          image: worker:latest
          resources:
        - name: log-shipper
          image: busybox
          resources:
            limits:
              cpu: "100m"
          securityContext:
            runAsNonRoot: false
"""

PLAN = {
    "resource_changes": [
        {"address": "aws_instance.web[0]", "type": "aws_instance",
         "change": {"actions": ["create"]}},
        {"address": "aws_security_group.web", "type": "aws_security_group",
         "change": {"actions": ["update"]}},
        {"address": "aws_db_instance.main", "type": "aws_db_instance",
         "change": {"actions": ["delete", "create"]}},
        {"address": "aws_s3_bucket.audit_logs", "type": "aws_s3_bucket",
         "change": {"actions": ["delete"]}},
        {"address": "aws_iam_role.app", "type": "aws_iam_role",
         "change": {"actions": ["no-op"]}},
        {"address": "aws_instance.bastion", "type": "aws_instance",
         "change": {"actions": ["create", "delete"]}},
    ]
}

PROTECTED = {"aws_db_instance", "aws_rds_cluster", "aws_s3_bucket"}

print("## The main problem: linting Kubernetes manifests\n")
print("Input: four documents. One healthy Deployment, a Service, an empty document left by a\n"
      "stray `---`, and a Deployment with two containers that would never survive review.\n")
print("```yaml")
print(MANIFESTS.rstrip())
print("```\n")

print("First the helper the whole lint turns on, `image_tag(...)`:\n")
print("```python")
for image in ("registry.internal:5000/api:1.4.2", "worker:latest", "busybox",
              "api@sha256:9f86d081884c7d65"):
    print(f"image_tag({image!r})".ljust(48) + f" -> {reference.image_tag(image)!r}")
print("```\n")

print("Reading that: the registry port `:5000` is not a tag, and a digest counts as pinned.\n"
      "A bare `busybox` has no tag at all, which is the same risk as `:latest`.\n")

findings = reference.lint_manifests(MANIFESTS)

print(f"Now the lint itself, `lint_manifests(text)` -> {len(findings)} findings:\n")
print("```text")
for f in findings:
    print(f"{f['kind']}/{f['name']} [{f['container']}] {f['rule']}: {f['message']}")
print("```\n")

print("One finding in full, so the shape is clear:\n")
print("```json")
print(json.dumps(findings[0], indent=2))
print("```\n")

print("Reading that: 8 findings, all from one Deployment. The healthy `api` produces nothing,\n"
      "and the Service and the empty document are skipped rather than crashing the run — a\n"
      "linter that dies on a stray `---` gets switched off within a week.\n"
      "\n"
      "`worker` has no limits at all: `resources:` with nothing under it parses as null, not as\n"
      "an empty dict, which is the single most common way this code throws AttributeError.\n"
      "`log-shipper` sets cpu but not memory, and the finding names only what's actually\n"
      "missing so it can be fixed in one pass.\n"
      "\n"
      "The two run-as-non-root findings arrive by different routes, and that's the subtle bit:\n"
      "`worker` inherits nothing because the pod never set it, while `log-shipper` sets it to\n"
      "`false` explicitly. A container is allowed to override the pod, so this has to fall back\n"
      "on absence only — treat an explicit `false` as 'unset' and you hide the one container\n"
      "actually running as root.\n"
      "\n"
      "On call, this is the gate that stops a deploy: the script exits non-zero, and the list is\n"
      "what you paste into the PR.\n")

print("## The variant: guarding a Terraform plan\n")
print("Input, the interesting slice of `terraform show -json`:\n")
print("```json")
print(json.dumps(PLAN, indent=2))
print("```\n")

print("`summarize_plan(plan)` and `dangerous_changes(plan, protected_types)`:\n")
print("```python")
print(f"summarize_plan(plan)              -> {variant_reference.summarize_plan(PLAN)}")
print(f"dangerous_changes(plan, {{...}})    -> {variant_reference.dangerous_changes(PLAN, PROTECTED)}")
print("```\n")

print("Per-resource, `classify(actions)`:\n")
print("```python")
for rc in PLAN["resource_changes"]:
    actions = rc["change"]["actions"]
    print(f"{rc['address']:<28} {str(actions):<22} -> {variant_reference.classify(actions)!r}")
print("```\n")

print("Reading that: six changes, but only five counted, because the `no-op` classifies as None\n"
      "and is ignored. Both delete/create orderings are a replace, including the\n"
      "create_before_destroy on `aws_instance.bastion` — it still destroys the old instance.\n"
      "Only the two protected types reach the danger list: the RDS replace and the audit-log\n"
      "bucket deletion. That's the pipeline failing loudly rather than someone spotting\n"
      "`1 to destroy` in 300 lines of plan output at 6pm on a Friday.")
