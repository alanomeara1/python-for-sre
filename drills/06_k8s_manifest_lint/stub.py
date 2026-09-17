"""Kubernetes manifest linter: the checks a reviewer does by eye, automated.

Spec: drills/06_k8s_manifest_lint/README.md
"""

from pathlib import Path

import yaml


def image_tag(image: str) -> str | None:
    raise NotImplementedError


def lint_manifests(text: str) -> list[dict]:
    raise NotImplementedError


def lint_file(path: str | Path) -> list[dict]:
    raise NotImplementedError
