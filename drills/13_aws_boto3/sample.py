"""Run the drill 13 reference against moto and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift.
moto generates a random id for every instance and volume, so each one is substituted
for a stable placeholder (i-0aaa..., vol-0aaa...) before printing. That substitution is
the `stable()` helper below, and nothing else here varies.
"""

import os
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Fake credentials BEFORE boto3 builds a client, so nothing can reach a real account.
os.environ.update(
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_SESSION_TOKEN="testing",
    AWS_DEFAULT_REGION="eu-west-1",
)
os.environ.pop("AWS_PROFILE", None)

import boto3
from moto import mock_aws

import reference
import variant_reference

REGION = "eu-west-1"
AMI = "ami-12c6146b"          # a fixed id: moto's describe_images is slow
REQUIRED = {"Owner", "Env", "CostCenter"}

_placeholders: dict[str, str] = {}


def stable(text: str) -> str:
    """Swap moto's random ids for fixed ones, so the sample output never changes."""
    for real, fake in _placeholders.items():
        text = text.replace(real, fake)
    return text


def register(real_id: str, label: str) -> str:
    _placeholders[real_id] = label
    return real_id


print("## The main problem: EC2 hygiene\n")

with mock_aws():
    ec2 = boto3.client("ec2", region_name=REGION)

    # Three volumes: one attached to a running instance, two left behind by deleted ones.
    attached_vol = register(ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=100)["VolumeId"],
                            "vol-0attached")
    orphan_vol = register(ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=500)["VolumeId"],
                          "vol-0orphan500")
    # moto truncates CreateTime to the second, and find_unattached_volumes sorts on
    # (created, id). Created in the same second, the tie would break on moto's RANDOM id and
    # this sample's output would flip between runs. One second apart makes the order real.
    time.sleep(1.1)
    small_orphan = register(ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=8)["VolumeId"],
                            "vol-0orphan8")
    # Fixed labels for the two creation times, so an order flip would be VISIBLE in the diff
    # rather than hidden by relabelling whatever came first.
    age_label = {orphan_vol: "<created first>", small_orphan: "<created 1s later>",
                 attached_vol: "<created first>"}

    def launch(tags=None):
        kwargs = {"ImageId": AMI, "MinCount": 1, "MaxCount": 1,
                  "Placement": {"AvailabilityZone": f"{REGION}a"}}
        if tags:
            kwargs["TagSpecifications"] = [
                {"ResourceType": "instance", "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}
            ]
        return ec2.run_instances(**kwargs)["Instances"][0]["InstanceId"]

    tagged = register(launch({"Owner": "platform", "Env": "prod", "CostCenter": "CC-1000"}),
                      "i-0tagged")
    half_tagged = register(launch({"Owner": "platform"}), "i-0halftagged")
    untagged = register(launch(), "i-0untagged")
    doomed = register(launch({"Owner": "platform", "Env": "dev", "CostCenter": "CC-2000"}),
                      "i-0terminated")

    ec2.attach_volume(VolumeId=attached_vol, InstanceId=tagged, Device="/dev/sdf")
    ec2.terminate_instances(InstanceIds=[doomed])

    print("The account, as moto sees it:\n")
    print("```text")
    print(f"{stable(attached_vol):<16} 100 GiB  attached to {stable(tagged)}")
    print(f"{stable(orphan_vol):<16} 500 GiB  available (nothing is using it)")
    print(f"{stable(small_orphan):<16}   8 GiB  available")
    print()
    print(f"{stable(tagged):<16} running     Owner, Env, CostCenter")
    print(f"{stable(half_tagged):<16} running     Owner only")
    print(f"{stable(untagged):<16} running     no tags at all")
    print(f"{stable(doomed):<16} terminated  fully tagged")
    print("```\n")

    print("`find_unattached_volumes(ec2)`:\n")
    print("```python")
    for volume in reference.find_unattached_volumes(ec2):
        # The real CreateTime is today's date, so print the fixed label instead.
        print(f"    {stable(volume['id']):<16} {volume['size']:>4} GiB   {age_label[volume['id']]}")
    print("```\n")

    print("Reading that: only the two `available` volumes come back, and the attached one is\n"
          "filtered out server-side rather than in Python — fewer bytes over the wire, and it\n"
          "scales to an account with 40,000 volumes. That 500 GiB orphan is roughly €50 a month\n"
          "for nothing. Oldest first, so the longest-running waste is at the top.\n")

    print(f"`find_instances_missing_tags(ec2, required={{'CostCenter', 'Env', 'Owner'}})`:\n")
    print("```python")
    # Sort on the PLACEHOLDER, not the real id: moto's ids are random, so sorting on them
    # would shuffle these two rows between runs.
    findings = reference.find_instances_missing_tags(ec2, REQUIRED).items()
    for instance_id, missing in sorted(findings, key=lambda item: stable(item[0])):
        print(f"    {stable(instance_id):<16} missing {missing}")
    print("```\n")

    print("Reading that: the fully tagged instance is absent, as is the terminated one — a\n"
          "terminated instance costs nothing and cannot be tagged, so reporting it is noise, and a\n"
          "compliance report full of noise is one nobody reads. The untagged instance has no\n"
          "`Tags` key at all in the API response, not an empty list, which is exactly the case a\n"
          "naive `instance['Tags']` would crash on.\n")

    print("`stop_instances(...)`, which defaults to a dry run:\n")
    print("```python")
    targets = [half_tagged, untagged]
    would = reference.stop_instances(ec2, targets, dry_run=True)
    print(f"stop_instances(ec2, targets, dry_run=True)  -> {[stable(i) for i in would]}")
    print("    (nothing was stopped: AWS reports a successful dry run by RAISING DryRunOperation)")
    stopped = reference.stop_instances(ec2, targets, dry_run=False)
    print(f"stop_instances(ec2, targets, dry_run=False) -> {[stable(i) for i in stopped]}")
    states = {}
    for reservation in ec2.describe_instances(InstanceIds=targets)["Reservations"]:
        for instance in reservation["Instances"]:
            states[stable(instance["InstanceId"])] = instance["State"]["Name"]
    print(f"    states afterwards: {dict(sorted(states.items()))}")
    print(f"stop_instances(ec2, [], dry_run=False)      -> {reference.stop_instances(ec2, [], dry_run=False)}")
    print("    (an empty list never reaches the API: on many EC2 calls it means EVERYTHING)")
    print("```\n")

    print("Reading that: the dry run returns the ids it *would* stop, because with `DryRun=True`\n"
          "there is no success response to inspect — the happy path lives in the `except` block.\n"
          "Only `DryRunOperation` is treated that way; `UnauthorizedOperation` is re-raised, or the\n"
          "safety check would cheerfully report 'would succeed' for a call your role cannot make.\n")

print("## The variant: S3 audit\n")

with mock_aws():
    s3 = boto3.client("s3", region_name=REGION)
    ALL_BLOCKED = {"BlockPublicAcls": True, "IgnorePublicAcls": True,
                   "BlockPublicPolicy": True, "RestrictPublicBuckets": True}

    def make_bucket(name, versioning=None, encryption=False, public_block=None):
        s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": REGION})
        if versioning:
            s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": versioning})
        if encryption:
            s3.put_bucket_encryption(Bucket=name, ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]})
        if public_block is not None:
            s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration=public_block)

    make_bucket("prod-backups", versioning="Enabled", encryption=True, public_block=ALL_BLOCKED)
    make_bucket("legacy-dumps")
    make_bucket("marketing-assets", versioning="Suspended", encryption=True,
                public_block={**ALL_BLOCKED, "RestrictPublicBuckets": False})

    print("Three buckets, set up differently:\n")
    print("```text")
    print("prod-backups      versioning Enabled    SSE-KMS      all four public-access flags on")
    print("legacy-dumps      never configured      none         no public access block at all")
    print("marketing-assets  versioning Suspended  SSE-KMS      three of four flags on")
    print("```\n")

    print("`audit_buckets(s3)`:\n")
    print("```python")
    for bucket, issues in sorted(variant_reference.audit_buckets(s3).items()):
        print(f"    {bucket:<18} {issues}")
    print("```\n")

    print("Reading that: `prod-backups` is clean. `marketing-assets` is flagged because\n"
          "`Suspended` is not `Enabled` — versioning that was turned off still leaves you without\n"
          "recovery — and because three of four public-access flags is not protection; `all()` of\n"
          "the four or it doesn't count. `legacy-dumps` trips every rule.\n")

    print("A caveat this drill states honestly: moto reports a brand-new bucket as having no\n"
          "default encryption, but since January 2023 real AWS applies SSE-S3 to every new bucket,\n"
          "so `no-default-encryption` rarely fires in production. The rule worth shipping is\n"
          "'not SSE-KMS with our own key', which `prod-backups` would pass and a default-encrypted\n"
          "bucket would not.\n")

    for key, size in [("logs/app-001.gz", 1_048_576),
                      ("logs/app-002.gz", 2_097_152),
                      ("logs/app-003.gz", 4096),
                      ("reports/q3.pdf", 999)]:
        s3.put_object(Bucket="prod-backups", Key=key, Body=b"x" * size)

    # moto stamps LastModified with the real clock, so `now` is derived from the objects
    # themselves: 100 days after they were written. That keeps their AGE fixed at 100 days
    # whenever this runs, which is what makes the two cutoffs below reproducible.
    newest = max(o["LastModified"] for o in s3.list_objects_v2(Bucket="prod-backups")["Contents"])
    NOW = newest + timedelta(days=100)

    print("`stale_objects(...)`, with `now` set 100 days after the objects were written:\n")
    print("```python")
    print("stale_objects(s3, 'prod-backups', prefix='logs/', older_than_days=90, now=NOW)")
    for obj in variant_reference.stale_objects(s3, "prod-backups", "logs/", 90, NOW):
        print(f"    {obj['key']:<18} {obj['size']:>9,} bytes")
    print()
    print("stale_objects(s3, 'prod-backups', prefix='logs/', older_than_days=200, now=NOW)")
    print(f"    -> {variant_reference.stale_objects(s3, 'prod-backups', 'logs/', 200, NOW)}")
    print("```\n")

    print("Reading that: at a 90-day cutoff all three log objects are stale, because they are 100\n"
          "days old; at 200 days none are, and an empty list is the correct answer for a cleanup\n"
          "job to do nothing with. `reports/q3.pdf` never appears either way — that is the\n"
          "`prefix` filter doing its job server-side, so a bucket with a billion keys doesn't have\n"
          "to be listed in full. `now` is a parameter rather than `datetime.now()` precisely so a\n"
          "test, or a sample like this one, can pin it; it must be timezone-aware, because S3\n"
          "returns aware timestamps and comparing aware with naive raises TypeError.")
