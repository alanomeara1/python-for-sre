MANIFESTS = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: good
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
      containers:
        - name: web
          image: registry.internal:5000/web:1.4.2
          readinessProbe:
            httpGet: {path: /healthz, port: 8080}
          resources:
            limits: {cpu: 500m, memory: 256Mi}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bad
spec:
  template:
    spec:
      containers:
        - name: api
          image: api:latest
          resources:
            limits: {memory: 128Mi}
        - name: sidecar
          image: envoy@sha256:0123abcd
          readinessProbe: {tcpSocket: {port: 9901}}
          resources:
          securityContext:
            runAsNonRoot: true
---
---
apiVersion: v1
kind: Service
metadata:
  name: good
spec:
  ports: [{port: 80}]
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
      containers:
        - name: postgres
          image: registry.internal:5000/postgres
          readinessProbe: {exec: {command: [pg_isready]}}
          resources:
            limits: {cpu: "1", memory: 1Gi}
          securityContext:
            runAsNonRoot: false
"""


def keys(findings):
    return [(f["kind"], f["name"], f["container"], f["rule"]) for f in findings]


def test_image_tag(solution):
    assert solution.image_tag("nginx:1.25") == "1.25"
    assert solution.image_tag("nginx") is None
    assert solution.image_tag("registry:5000/app") is None
    assert solution.image_tag("registry:5000/team/app:2.0") == "2.0"
    assert solution.image_tag("app@sha256:abc") == "sha256:abc"


def test_lint_exact_findings_sorted(solution):
    assert keys(solution.lint_manifests(MANIFESTS)) == [
        ("Deployment", "bad", "api", "image-tag"),
        ("Deployment", "bad", "api", "readiness-probe"),
        ("Deployment", "bad", "api", "resource-limits"),
        ("Deployment", "bad", "api", "run-as-non-root"),
        ("Deployment", "bad", "sidecar", "resource-limits"),
        ("StatefulSet", "db", "postgres", "image-tag"),
        ("StatefulSet", "db", "postgres", "run-as-non-root"),
    ]


def test_findings_have_messages(solution):
    findings = solution.lint_manifests(MANIFESTS)
    assert all(isinstance(f["message"], str) and f["message"] for f in findings)
    api_limits = next(f for f in findings if f["container"] == "api" and f["rule"] == "resource-limits")
    assert "cpu" in api_limits["message"] and "memory" not in api_limits["message"]


def test_non_workloads_and_empty_docs_ignored(solution):
    text = "---\n---\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: x}\ndata: {a: b}\n"
    assert solution.lint_manifests(text) == []


def test_workload_without_containers_does_not_crash(solution):
    text = "apiVersion: apps/v1\nkind: DaemonSet\nmetadata: {name: empty}\nspec: {}\n"
    assert solution.lint_manifests(text) == []


def test_daemonset_is_checked(solution):
    text = """\
kind: DaemonSet
metadata: {name: agent}
spec:
  template:
    spec:
      containers:
        - {name: node-exporter, image: "node-exporter:v1.8.0"}
"""
    assert set(f["rule"] for f in solution.lint_manifests(text)) == {
        "resource-limits", "readiness-probe", "run-as-non-root"}


def test_lint_file(solution, tmp_path):
    path = tmp_path / "all.yaml"
    path.write_text(MANIFESTS)
    assert len(solution.lint_file(path)) == 7
