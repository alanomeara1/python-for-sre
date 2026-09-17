"""Terraform plan guard: summarise a JSON plan and catch destructive changes."""

import json
from collections import Counter
from pathlib import Path

# Lists aren't hashable, so the actions list is looked up as a tuple.
ACTION_KINDS = {
    ("create",): "create",
    ("update",): "update",
    ("delete",): "delete",
    ("delete", "create"): "replace",
    ("create", "delete"): "replace",     # create_before_destroy still destroys
}

DESTRUCTIVE = {"delete", "replace"}


def load_plan(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def classify(actions: list[str]) -> str | None:
    return ACTION_KINDS.get(tuple(actions))  # no-op / read -> None


def summarize_plan(plan: dict) -> dict:
    counts = Counter()
    # A plan with nothing to do can omit resource_changes entirely.
    for rc in plan.get("resource_changes", []):
        kind = classify(rc["change"]["actions"])
        if kind:
            counts[kind] += 1
    # Every key always present: callers never need .get().
    return {kind: counts[kind] for kind in ("create", "update", "delete", "replace")}


def dangerous_changes(plan: dict, protected_types: set[str]) -> list[str]:
    return sorted(
        rc["address"]
        for rc in plan.get("resource_changes", [])
        if rc["type"] in protected_types and classify(rc["change"]["actions"]) in DESTRUCTIVE
    )


if __name__ == "__main__":
    import sys

    plan = load_plan(sys.argv[1])
    print(summarize_plan(plan))
    danger = dangerous_changes(plan, {"aws_db_instance", "aws_rds_cluster", "aws_s3_bucket"})
    for address in danger:
        print(f"DANGER: {address} will be destroyed")
    sys.exit(2 if danger else 0)
