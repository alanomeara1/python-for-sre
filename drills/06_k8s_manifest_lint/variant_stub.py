"""Terraform plan guard: summarise a JSON plan and catch destructive changes.

Spec: drills/06_k8s_manifest_lint/variant.md
"""

from pathlib import Path


def load_plan(path: str | Path) -> dict:
    raise NotImplementedError


def classify(actions: list[str]) -> str | None:
    raise NotImplementedError


def summarize_plan(plan: dict) -> dict:
    raise NotImplementedError


def dangerous_changes(plan: dict, protected_types: set[str]) -> list[str]:
    raise NotImplementedError
