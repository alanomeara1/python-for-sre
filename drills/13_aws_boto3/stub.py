"""EC2 hygiene: unattached EBS volumes, missing mandatory tags, safe instance stop.

Spec: drills/13_aws_boto3/README.md
"""

from botocore.exceptions import ClientError


def find_unattached_volumes(ec2) -> list[dict]:
    raise NotImplementedError


def find_instances_missing_tags(ec2, required: set[str]) -> dict[str, list[str]]:
    raise NotImplementedError


def stop_instances(ec2, instance_ids: list[str], dry_run: bool = True) -> list[str]:
    raise NotImplementedError
