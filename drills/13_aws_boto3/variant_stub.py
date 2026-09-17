"""S3 audit: versioning, default encryption, public access block, stale objects.

Spec: drills/13_aws_boto3/variant.md
"""

from datetime import datetime

from botocore.exceptions import ClientError


def audit_buckets(s3) -> dict[str, list[str]]:
    raise NotImplementedError


def stale_objects(s3, bucket: str, prefix: str, older_than_days: int, now: datetime) -> list[dict]:
    raise NotImplementedError
