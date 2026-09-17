# 06 · Variant: Terraform plan guard

Same shape as the main drill (walk nested machine-generated data, classify, report sorted
results), but for Terraform instead of Kubernetes.

## The task

> Someone applied a plan last quarter that replaced the production database. Write a check
> for CI: read the JSON plan, summarise how many resources will be created, updated, deleted
> and replaced, and list every delete or replace that touches a protected resource type.

`terraform show -json plan.out` produces (trimmed):

```json
{
  "resource_changes": [
    {"address": "aws_db_instance.main", "type": "aws_db_instance",
     "change": {"actions": ["delete", "create"]}},
    {"address": "aws_instance.web[0]", "type": "aws_instance",
     "change": {"actions": ["update"]}},
    {"address": "aws_s3_bucket.logs", "type": "aws_s3_bucket",
     "change": {"actions": ["no-op"]}}
  ]
}
```

`actions` is one of: `["no-op"]`, `["read"]`, `["create"]`, `["update"]`, `["delete"]`,
`["delete", "create"]` (replace, destroy first) or `["create", "delete"]` (replace with
`create_before_destroy`). A plan with no changes may have no `resource_changes` key at all.

## Contract

```python
def load_plan(path: str | Path) -> dict

def classify(actions: list[str]) -> str | None
    # "create" | "update" | "delete" | "replace", or None for no-op/read

def summarize_plan(plan: dict) -> dict
    # -> {"create": 1, "update": 2, "delete": 0, "replace": 1}   all four keys, always

def dangerous_changes(plan: dict, protected_types: set[str]) -> list[str]
    # addresses whose action is delete or replace AND whose type is protected, sorted
```

## Say this out loud

- "I map the action *list* to a kind with a tuple-keyed dict. Lists aren't hashable, so I convert with `tuple()`."
- "Both replace orderings are dangerous. `create_before_destroy` still destroys the old one."
- "All four summary keys are always present, so downstream code and dashboards never need `.get`."
- "In CI this should fail the pipeline and require an explicit human override label, not just print."
  Terraform's own `prevent_destroy` lifecycle rule is the belt to this script's braces.
