from datetime import timedelta

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from moto import mock_aws

REGION = "eu-west-1"
ALL_BLOCKED = {"BlockPublicAcls": True, "IgnorePublicAcls": True,
               "BlockPublicPolicy": True, "RestrictPublicBuckets": True}


class PaginatorSpy:
    """Wraps a real client and records which paginators the code under test asked for."""

    def __init__(self, client):
        self._client = client
        self.paginators = []

    def get_paginator(self, name):
        self.paginators.append(name)
        return self._client.get_paginator(name)

    def __getattr__(self, name):
        return getattr(self._client, name)


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def s3(aws_env):
    with mock_aws():
        yield boto3.client("s3", region_name=REGION)


def make_bucket(s3, name, versioning=None, encryption=False, public_block=None):
    s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": REGION})
    if versioning:
        s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": versioning})
    if encryption:
        s3.put_bucket_encryption(Bucket=name, ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]})
    if public_block is not None:
        s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration=public_block)


def test_audit_buckets(variant, s3):
    make_bucket(s3, "clean-bucket", versioning="Enabled", encryption=True, public_block=ALL_BLOCKED)
    make_bucket(s3, "bare-bucket")
    make_bucket(s3, "suspended-bucket", versioning="Suspended", encryption=True,
                public_block={**ALL_BLOCKED, "RestrictPublicBuckets": False})

    spy = PaginatorSpy(s3)
    assert variant.audit_buckets(spy) == {
        "clean-bucket": [],
        "bare-bucket": ["versioning-disabled", "no-default-encryption", "public-access-not-blocked"],
        "suspended-bucket": ["versioning-disabled", "public-access-not-blocked"],
    }
    assert "list_buckets" in spy.paginators


def test_audit_buckets_no_buckets(variant, s3):
    assert variant.audit_buckets(s3) == {}


def test_audit_buckets_access_denied_propagates(variant, aws_env):
    client = boto3.client("s3", region_name=REGION)
    with Stubber(client) as stub:
        stub.add_response("list_buckets", {"Buckets": [{"Name": "locked-bucket"}]})
        stub.add_response("get_bucket_versioning", {"Status": "Enabled"})
        stub.add_client_error("get_bucket_encryption", service_error_code="AccessDenied", http_status_code=403)
        with pytest.raises(ClientError) as excinfo:
            variant.audit_buckets(client)
    assert excinfo.value.response["Error"]["Code"] == "AccessDenied"


def upload(s3, bucket, *keys):
    for key in keys:
        s3.put_object(Bucket=bucket, Key=key, Body=b"x" * len(key))
    return s3.head_object(Bucket=bucket, Key=keys[0])["LastModified"]


def test_stale_objects_prefix_and_cutoff(variant, s3):
    make_bucket(s3, "logs-bucket")
    written = upload(s3, "logs-bucket", "app/2026/b.log", "app/2026/a.log", "db/old.log")

    spy = PaginatorSpy(s3)
    ten_days_later = written + timedelta(days=10)
    result = variant.stale_objects(spy, "logs-bucket", "app/", 7, now=ten_days_later)

    assert [o["key"] for o in result] == ["app/2026/a.log", "app/2026/b.log"]
    assert result[0]["size"] == len("app/2026/a.log")
    assert set(result[0]) == {"key", "size", "last_modified"}
    assert "list_objects_v2" in spy.paginators

    assert variant.stale_objects(s3, "logs-bucket", "app/", 30, now=ten_days_later) == []


def test_stale_objects_no_matching_prefix(variant, s3):
    make_bucket(s3, "logs-bucket")
    written = upload(s3, "logs-bucket", "app/a.log")
    assert variant.stale_objects(s3, "logs-bucket", "nothing-here/", 1, now=written + timedelta(days=5)) == []
