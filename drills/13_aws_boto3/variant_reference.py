"""S3 audit: versioning, default encryption, public access block, stale objects."""

from datetime import datetime, timedelta

from botocore.exceptions import ClientError


def _error_code(e: ClientError) -> str:
    return e.response["Error"]["Code"]


def audit_buckets(s3) -> dict[str, list[str]]:
    report = {}
    for page in s3.get_paginator("list_buckets").paginate():
        for bucket in page["Buckets"]:
            name = bucket["Name"]
            issues = []

            # "Status" is absent if versioning was never configured.
            if s3.get_bucket_versioning(Bucket=name).get("Status") != "Enabled":
                issues.append("versioning-disabled")

            try:
                s3.get_bucket_encryption(Bucket=name)
            except ClientError as e:
                # Only "not configured" is a finding. AccessDenied must not look like a clean bucket.
                if _error_code(e) != "ServerSideEncryptionConfigurationNotFoundError":
                    raise
                issues.append("no-default-encryption")

            try:
                block = s3.get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
                fully_blocked = all(block.values())
            except ClientError as e:
                if _error_code(e) != "NoSuchPublicAccessBlockConfiguration":
                    raise
                fully_blocked = False
            if not fully_blocked:
                issues.append("public-access-not-blocked")

            report[name] = issues
    return report


def stale_objects(s3, bucket: str, prefix: str, older_than_days: int, now: datetime) -> list[dict]:
    cutoff = now - timedelta(days=older_than_days)
    stale = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):        # key is missing when nothing matches
            if obj["LastModified"] < cutoff:
                stale.append({"key": obj["Key"], "size": obj["Size"], "last_modified": obj["LastModified"]})
    return sorted(stale, key=lambda o: (o["last_modified"], o["key"]))
