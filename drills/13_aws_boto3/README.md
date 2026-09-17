# 13 · AWS with boto3: unattached volumes, tag compliance, safe stop

**Why this drill:** "Write a script to find waste / non-compliant resources in our AWS account" is
the most common cloud-flavoured SRE exercise, and cost and hygiene are exactly what an SRE Manager
gets asked about. The patterns (paginators, nested responses, `ClientError` codes, `DryRun`) apply
to every AWS service.

## The task, as an interviewer would say it

> Finance says our EC2 bill is creeping up. Write a script that finds EBS volumes that aren't
> attached to anything, and instances missing our mandatory tags (Owner, Env, CostCenter). Then give
> me a function to stop instances, and make it safe by default.

## Contract (what the tests call)

Every function takes a boto3 **client** as its first argument. Don't create clients inside the functions.

```python
def find_unattached_volumes(ec2) -> list[dict]
    # volumes with status "available" (i.e. not attached)
    # -> [{"id": "vol-...", "size": 100, "created": datetime}, ...]
    # sorted by (created, id), oldest first
    # MUST use the describe_volumes paginator, filtering server-side

def find_instances_missing_tags(ec2, required: set[str]) -> dict[str, list[str]]
    # {instance_id: sorted list of missing tag keys}, only for instances missing at least one
    # ignore instances that are "terminated" or "shutting-down"
    # MUST use the describe_instances paginator

def stop_instances(ec2, instance_ids: list[str], dry_run: bool = True) -> list[str]
    # dry_run=True: call StopInstances with DryRun=True. AWS signals "you WOULD be allowed" by raising
    #   ClientError with code "DryRunOperation" -> return the ids. Any other ClientError -> re-raise.
    # dry_run=False: stop them, return the ids from the response's StoppingInstances.
    # [] -> return [] without calling AWS.
```

```python
if __name__ == "__main__":
    ec2 = boto3.client("ec2", region_name="eu-west-1")
    for vol in find_unattached_volumes(ec2):
        print(vol["id"], vol["size"], "GiB, created", vol["created"])
```

## Patterns you are drilling

- `paginator = ec2.get_paginator("describe_volumes")` then `for page in paginator.paginate(Filters=[...]):`
- Filters syntax: `[{"Name": "status", "Values": ["available"]}]`
- EC2's awkward nesting: `page["Reservations"]` → `reservation["Instances"]`
- `instance.get("Tags", [])`: the key is **absent** when there are no tags
- Set arithmetic: `required - {t["Key"] for t in tags}`
- `except ClientError as e: if e.response["Error"]["Code"] == "...":`, then a bare `raise` for everything else
- Tests: `with mock_aws():` (moto) for behaviour, `botocore.stub.Stubber` to force a specific AWS error

## Say this out loud (what the interviewer listens for)

- "Paginators, always. `describe_instances` returns at most 1000 per call, and the bug where the
  script only sees the first page never shows up in a test account."
- "I filter server-side with `Filters`. Less data over the wire and fewer API calls, which matters
  when you hit API rate limits across 20 accounts."
- "The client is injected: testable with moto, and the caller controls region, profile and retries
  (`botocore.config.Config(retries={'mode': 'adaptive'})`)."
- "Destructive actions default to dry run. I'd also log exactly what would be touched and require an
  explicit `--apply` flag in the CLI."
- Manager-level: "A script is the first step. The durable fix is tag policies in AWS Organizations or
  an SCP that denies `RunInstances` without the tags, plus a scheduled report with an owner per finding.
  Otherwise we clean up once and drift back."
- "Unattached isn't the same as unused. I'd snapshot before deleting and check CloudTrail for recent detaches."

## Traps

- Forgetting pagination (works in your sandbox, silently wrong in prod).
- `instance["Tags"]` → `KeyError` on untagged instances.
- Treating `DryRunOperation` as a failure. With `DryRun`, success *is* the exception.
- `except ClientError: pass`, which swallows `UnauthorizedOperation` and reports "would succeed".
- Region: a client with no region raises `NoRegionError`, and a script run against the wrong region
  finds nothing and looks clean. Print the region you're auditing.
