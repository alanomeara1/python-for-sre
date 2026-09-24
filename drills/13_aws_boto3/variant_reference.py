"""S3 audit: versioning, default encryption, public access block, stale objects.

Three checks, three different shapes of "not configured": a missing key, a ClientError,
and a ClientError OR four boolean flags. Telling "not configured" apart from "not
allowed" is the whole game. Full reasoning in EXPLAINED.md.
"""

from datetime import datetime, timedelta

from botocore.exceptions import ClientError


def _error_code(e: ClientError) -> str:
    # Every botocore error carries the AWS code here. Comparing codes, rather than message
    # text, is what keeps the handling precise.
    return e.response["Error"]["Code"]


def audit_buckets(s3) -> dict[str, list[str]]:
    report = {}
    for page in s3.get_paginator("list_buckets").paginate():
        for bucket in page["Buckets"]:
            name = bucket["Name"]
            issues = []

            # "Status" is absent if versioning was never configured.
            # != "Enabled" therefore catches both "never enabled" and "Suspended" in one test.
            if s3.get_bucket_versioning(Bucket=name).get("Status") != "Enabled":
                issues.append("versioning-disabled")

            try:
                s3.get_bucket_encryption(Bucket=name)
            except ClientError as e:
                # Only "not configured" is a finding. AccessDenied must not look like a clean bucket.
                # An audit that reports an unreadable bucket as clean is worse than no audit:
                # it manufactures false confidence.
                if _error_code(e) != "ServerSideEncryptionConfigurationNotFoundError":
                    raise
                issues.append("no-default-encryption")
                # Honest caveat: since Jan 2023 real AWS applies SSE-S3 to every new bucket, so
                # this rarely fires outside moto. The rule that earns its place in production is
                # "not SSE-KMS with our own key".

            try:
                block = s3.get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
                # Four flags, and partial protection is not protection: all() of the four.
                fully_blocked = all(block.values())
            except ClientError as e:
                # Here "absent" arrives as an error rather than a missing key -- a third shape
                # of "not configured" in the same function.
                if _error_code(e) != "NoSuchPublicAccessBlockConfiguration":
                    raise
                fully_blocked = False
            if not fully_blocked:
                issues.append("public-access-not-blocked")

            report[name] = issues
    return report


def stale_objects(s3, bucket: str, prefix: str, older_than_days: int, now: datetime) -> list[dict]:
    # `now` is injected, not datetime.now(): the test controls time exactly, with no sleeping and
    # no flakiness. It must be timezone-AWARE, because LastModified is UTC-aware and comparing
    # aware with naive raises TypeError.
    cutoff = now - timedelta(days=older_than_days)
    stale = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):        # key is missing when nothing matches
            if obj["LastModified"] < cutoff:
                stale.append({"key": obj["Key"], "size": obj["Size"], "last_modified": obj["LastModified"]})
    # At real scale you would not list objects at all: S3 Inventory plus Athena, or Storage Lens,
    # beats ListObjectsV2 over a billion keys on both cost and time.
    return sorted(stale, key=lambda o: (o["last_modified"], o["key"]))
