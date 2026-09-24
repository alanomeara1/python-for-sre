"""Terraform plan guard: summarise a JSON plan and catch destructive changes.

Same shape as the linter: classify each item, then report sorted results.
Full reasoning in EXPLAINED.md.
"""

import json
from collections import Counter
from pathlib import Path

# Lists aren't hashable, so the actions list is looked up as a tuple.
# A lookup table rather than a chain of `if actions == [...]`: the mapping is data,
# readable at a glance, and adding a case is one line.
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
    # None means "nothing worth reporting", not an error: the caller skips it.
    # .get rather than [] so an action combination we've never seen can't crash CI.
    return ACTION_KINDS.get(tuple(actions))  # no-op / read -> None


def summarize_plan(plan: dict) -> dict:
    counts = Counter()
    # A plan with nothing to do can omit resource_changes entirely, and that is the
    # case that runs on every quiet CI build, so it must not raise.
    for rc in plan.get("resource_changes", []):
        kind = classify(rc["change"]["actions"])
        if kind:
            counts[kind] += 1
    # A Counter only holds keys it has seen, so a plan with no deletions would have no
    # "delete" key and every dashboard would need a default. Fill all four instead.
    # Every key always present: callers never need .get().
    return {kind: counts[kind] for kind in ("create", "update", "delete", "replace")}


def dangerous_changes(plan: dict, protected_types: set[str]) -> list[str]:
    # Sorted so the output is stable in CI logs and diffable between runs.
    return sorted(
        rc["address"]
        for rc in plan.get("resource_changes", [])
        # Both replace orderings reach DESTRUCTIVE via classify(), which is the point:
        # create_before_destroy still destroys the old resource.
        if rc["type"] in protected_types and classify(rc["change"]["actions"]) in DESTRUCTIVE
    )


if __name__ == "__main__":
    import sys

    plan = load_plan(sys.argv[1])
    print(summarize_plan(plan))
    danger = dangerous_changes(plan, {"aws_db_instance", "aws_rds_cluster", "aws_s3_bucket"})
    for address in danger:
        print(f"DANGER: {address} will be destroyed")
    # Exit 2 fails the pipeline: a guard nobody is forced to read is decoration.
    sys.exit(2 if danger else 0)
