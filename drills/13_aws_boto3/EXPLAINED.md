# 13 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

---

## The mental model

Three functions, one shape:

```
find_unattached_volumes(ec2)          read  -> paginate, filter server-side, normalise, sort
find_instances_missing_tags(ec2, req) read  -> paginate, unwrap nesting, set difference
stop_instances(ec2, ids, dry_run)     WRITE -> safe by default, DryRun succeeds by raising
```

**The client is a parameter, never created inside.** Three reasons, and say all three:

1. **Testable.** The test hands you a moto-backed client, or a `Stubber` that forces a specific AWS
   error. A function that calls `boto3.client(...)` internally can only be tested against real AWS.
2. **The caller controls configuration** — region, profile, and retry behaviour
   (`botocore.config.Config(retries={"mode": "adaptive"})`), which matters when you're being throttled.
3. **One client, reused.** Creating a client parses large JSON service models and sets up a
   connection pool; doing that per call is slow for no benefit.

**Memory hook: inject the client, paginate everything, and make writes dry by default.**

---

## Chunk 1: Why paginators, every single time

```python
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page["Volumes"]:
```

### The failure this prevents

Nearly every AWS list/describe call is capped — `describe_instances` at roughly 1000 results,
`list_objects_v2` at 1000 keys. A plain `ec2.describe_instances()` returns **the first page and a
`NextToken`**, and if you ignore that token you have silently processed a fraction of the account.

What makes this dangerous rather than annoying: **it works perfectly in your sandbox.** Twelve
instances, one page, tests pass, ship it. In the production account it quietly reports that
everything is compliant. A cost report that under-reports and an audit that under-reports are worse
than none, because people trust them.

The paginator handles the token loop for you. It takes the same keyword arguments as the underlying
call, so nothing else about your code changes. The drill's tests wrap the client in a `PaginatorSpy`
and assert you actually asked for one — you can't sneak past with a direct call.

### Why filter server-side

`Filters=[{"Name": "status", "Values": ["available"]}]` makes AWS do the work. Filtering in Python
instead means transferring every volume in the account and burning API calls you'll want back when
you're rate-limited across twenty accounts. The filter syntax (a list of `{"Name", "Values"}` dicts,
`Values` always a list) is worth memorising because it's identical across EC2 APIs.

### Normalising the result

```python
            volumes.append({
                "id": volume["VolumeId"],
                "size": volume["Size"],
                "created": volume["CreateTime"],
            })
    return sorted(volumes, key=lambda v: (v["created"], v["id"]))
```

Returning your own small dicts rather than raw AWS responses keeps the caller (and your tests) away
from thirty irrelevant keys, and means a change in the API shape is absorbed in one place. Sorting
by `(created, id)` puts the oldest waste first — which is what finance wants — and the `id`
tie-break makes the output deterministic.

---

## Chunk 2: EC2's nesting, and the absent `Tags` key

```python
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                if instance["State"]["Name"] in ("terminated", "shutting-down"):
                    continue
                present = {tag["Key"] for tag in instance.get("Tags", [])}
                if absent := required - present:
                    missing[instance["InstanceId"]] = sorted(absent)
```

### Three loops, not two

`describe_instances` returns **Reservations**, each containing **Instances**. A reservation is one
`RunInstances` call, so asking for ten instances at once gives one reservation with ten instances.
It's a historical API shape that everybody forgets, and it's the most common mistake in this
question. You don't care about reservations at all — you just have to unwrap them.

### `instance.get("Tags", [])`, not `instance["Tags"]`

On an untagged instance the key is **absent entirely**, not an empty list. `instance["Tags"]` raises
`KeyError` on exactly the instances you're hunting for — the untagged ones. This is the single
highest-value habit in boto3 work: optional things are missing, not empty.

Note also that tags arrive as a *list of dicts*, `[{"Key": "Env", "Value": "prod"}]`, not a mapping.
A set comprehension over `tag["Key"]` gives you something you can do arithmetic with.

### Set difference

`required - present` is "what's in the required set and not in the tags", which is the whole
question in one expression. `sorted()` on the way out for deterministic output.

The walrus `if absent := required - present:` assigns and tests in one line: compute the difference
once, and only record instances that are actually missing something (an empty set is falsy).

### Why skip terminated instances

A terminated instance is gone: it costs nothing, and it can't be tagged. Reporting it is noise, and
a compliance report full of noise is a report nobody reads. `"shutting-down"` is the same thing
mid-flight. That judgement — filtering findings down to the ones someone can act on — is the
manager-level signal here.

---

## Chunk 3: `stop_instances`, and the inverted DryRun

```python
    if not instance_ids:
        return []
    try:
        response = ec2.stop_instances(InstanceIds=instance_ids, DryRun=dry_run)
    except ClientError as e:
        if dry_run and e.response["Error"]["Code"] == "DryRunOperation":
            return list(instance_ids)
        raise
    return [item["InstanceId"] for item in response["StoppingInstances"]]
```

### The empty-list guard comes first

Two reasons. It avoids a pointless API call (the test uses a `Stubber` with nothing queued, so *any*
call raises). And it's a habit worth burning in: across the EC2 API, an **empty or omitted** id list
on a `describe_*` call means *"all resources"*, not *"none"*. The same shape of mistake in a
different function is how people accidentally act on an entire account.

### With DryRun, success *is* an exception

This is genuinely counter-intuitive and worth saying out loud. When you pass `DryRun=True`, AWS
checks your permissions and then reports the result by **raising** `ClientError` with the code
`DryRunOperation`, meaning "you would have been allowed". There is no success response to inspect.

So the "happy path" for a dry run lives in the `except` block. If you're *not* allowed, you get a
different code — `UnauthorizedOperation` — and that must not be reported as "would succeed".

### Why `except ClientError: pass` is a disaster here

It's the tempting shortcut, and it turns your safety check into a lie: every dry run reports success,
including the ones that would fail on permissions. You'd discover this during the real run, halfway
through. Check the specific code, and **bare `raise`** everything else — bare `raise` re-raises the
current exception with its original traceback intact.

### Why `dry_run: bool = True`

Destructive functions default to safe. Someone calling `stop_instances(ec2, ids)` in a hurry, or
importing it into a notebook, gets a no-op rather than an outage. Pair it with an explicit `--apply`
flag at the CLI layer, and log exactly what *would* be touched.

---

## Why moto, and what the test fixtures are doing

```python
@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    ...
```

- **moto is an in-process fake AWS.** It intercepts botocore calls, so tests are fast, free,
  deterministic, offline, and can't be broken by someone else's changes in a shared account.
- **The fake credentials are a safety belt.** If the mock ever failed to engage, real credentials
  plus a real profile would send `stop_instances` at a real account. Deleting `AWS_PROFILE` and
  setting obviously-fake keys means the worst case is an auth error, not an outage.
- **`Stubber` does the job moto can't.** moto won't naturally produce `UnauthorizedOperation` or
  `AccessDenied`, so the tests queue that exact error on a real client to prove your error handling
  re-raises rather than swallowing it.
- **`AMI = "ami-12c6146b"` is hardcoded** because `describe_images` in moto is slow. Small thing,
  but it's why the suite runs in two seconds rather than twenty.

**Where moto and real AWS differ** matters for one rule in the variant, and the drill is honest
about it rather than pretending: see the variant notes below.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_find_unattached_volumes` | didn't use the paginator (the spy checks), wrong filter, or wrong sort order |
| `test_find_unattached_volumes_none` | crashed on an empty account instead of returning `[]` |
| `test_find_instances_missing_tags` | forgot the `Reservations` level, `instance["Tags"]` KeyError, or included terminated instances |
| `test_stop_instances_dry_run_by_default_changes_nothing` | `dry_run` didn't default to `True`, or you actually stopped them |
| `test_stop_instances_for_real` | returned the input ids instead of reading `StoppingInstances` |
| `test_stop_instances_empty_list_makes_no_call` | no early return, so an API call happened on an empty list |
| `test_stop_instances_dry_run_reraises_other_errors` | caught every `ClientError` instead of only `DryRunOperation` |
| `test_stop_instances_bad_id_raises` | swallowed a real error and reported success |

`NoRegionError` means the client was built without a region. In a script, print the region you're
auditing: a run against the wrong region finds nothing and looks beautifully clean.

---

## The variant: what actually changes

An S3 audit. Same skeleton, four differences:

1. **Three checks, three different shapes of "not configured".** Versioning returns a dict with
   **no `Status` key** when it was never enabled, so `.get("Status") != "Enabled"` catches both
   "never enabled" and "Suspended". Encryption raises a `ClientError`. Public access block *either*
   raises `NoSuchPublicAccessBlockConfiguration` *or* returns four flags of which any may be `False`
   (`all(block.values())`). Knowing that "absent" looks different in every API is the actual lesson.

2. **Telling "not configured" from "not allowed" is the whole game.** Both arrive as `ClientError`.
   Compare `e.response["Error"]["Code"]` and re-raise anything you didn't expect. An audit that
   reports a bucket as clean because it couldn't read the config is worse than no audit: it
   manufactures false confidence. This is the sentence to say out loud.

3. **`now` is a parameter, not `datetime.now()` inside.** The test then controls time exactly, with
   no sleeping and no flakiness. Note that `LastModified` is timezone-**aware** UTC, so comparing it
   with a naive datetime raises `TypeError` — the same aware/naive trap as drill 01.

4. **`page.get("Contents", [])`** because a page with no matching objects has no `Contents` key at
   all. Same "absent, not empty" rule as EC2's tags.

**The honest caveat, worth repeating in an interview:** since January 2023 AWS applies SSE-S3 to
every new bucket, so on real AWS `get_bucket_encryption` almost always succeeds with AES256 and the
`no-default-encryption` finding rarely fires. moto (5.2) still returns not-found for a new bucket,
which is why this drill can test that path at all. The rule that actually earns its place in
production is "not encrypted with SSE-KMS using our own key". Knowing where your test double
diverges from reality is exactly the kind of thing that separates a script that looks right from one
that is.

At scale, say the last one too: **don't list a billion objects.** S3 Inventory plus Athena, or
Storage Lens, is cheaper and faster than `ListObjectsV2` in a loop.
