import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from moto import mock_aws

REGION = "eu-west-1"
REQUIRED = {"Owner", "Env", "CostCenter"}
AMI = "ami-12c6146b"   # fixed id: describe_images in moto is slow (~0.5s per call)


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
    # Never let a test touch a real account through the developer's profile.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def ec2(aws_env):
    with mock_aws():
        yield boto3.client("ec2", region_name=REGION)


def launch(ec2, tags=None, count=1):
    kwargs = {"ImageId": AMI, "MinCount": count, "MaxCount": count,
              "Placement": {"AvailabilityZone": f"{REGION}a"}}
    if tags:
        kwargs["TagSpecifications"] = [{"ResourceType": "instance",
                                        "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}]
    return [i["InstanceId"] for i in ec2.run_instances(**kwargs)["Instances"]]


def state(ec2, instance_id):
    reservations = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"]
    return reservations[0]["Instances"][0]["State"]["Name"]


def test_find_unattached_volumes(solution, ec2):
    [instance] = launch(ec2)
    attached = ec2.create_volume(Size=50, AvailabilityZone=f"{REGION}a")["VolumeId"]
    ec2.attach_volume(VolumeId=attached, InstanceId=instance, Device="/dev/sdf")
    free_a = ec2.create_volume(Size=100, AvailabilityZone=f"{REGION}a")["VolumeId"]
    free_b = ec2.create_volume(Size=8, AvailabilityZone=f"{REGION}b")["VolumeId"]

    spy = PaginatorSpy(ec2)
    result = solution.find_unattached_volumes(spy)

    assert {v["id"] for v in result} == {free_a, free_b}
    assert {v["id"]: v["size"] for v in result} == {free_a: 100, free_b: 8}
    assert all(set(v) == {"id", "size", "created"} for v in result)
    assert result == sorted(result, key=lambda v: (v["created"], v["id"]))
    assert "describe_volumes" in spy.paginators


def test_find_unattached_volumes_none(solution, ec2):
    launch(ec2)                                   # root volume is attached
    assert solution.find_unattached_volumes(ec2) == []


def test_find_instances_missing_tags(solution, ec2):
    [compliant] = launch(ec2, {"Owner": "sre", "Env": "prod", "CostCenter": "42", "Extra": "x"})
    [partial] = launch(ec2, {"Owner": "sre"})
    [untagged] = launch(ec2)
    [gone] = launch(ec2)
    ec2.terminate_instances(InstanceIds=[gone])

    spy = PaginatorSpy(ec2)
    result = solution.find_instances_missing_tags(spy, REQUIRED)

    assert result == {
        partial: ["CostCenter", "Env"],
        untagged: ["CostCenter", "Env", "Owner"],
    }
    assert compliant not in result and gone not in result
    assert "describe_instances" in spy.paginators


def test_stop_instances_dry_run_by_default_changes_nothing(solution, ec2):
    ids = launch(ec2, count=2)
    assert sorted(solution.stop_instances(ec2, ids)) == sorted(ids)
    assert [state(ec2, i) for i in ids] == ["running", "running"]


def test_stop_instances_for_real(solution, ec2):
    ids = launch(ec2, count=2)
    assert sorted(solution.stop_instances(ec2, ids, dry_run=False)) == sorted(ids)
    assert all(state(ec2, i) in ("stopping", "stopped") for i in ids)


def test_stop_instances_empty_list_makes_no_call(solution, aws_env):
    client = boto3.client("ec2", region_name=REGION)
    with Stubber(client):                         # any unexpected API call would raise
        assert solution.stop_instances(client, [], dry_run=False) == []


def test_stop_instances_dry_run_reraises_other_errors(solution, aws_env):
    client = boto3.client("ec2", region_name=REGION)
    with Stubber(client) as stub:
        stub.add_client_error("stop_instances", service_error_code="UnauthorizedOperation",
                              http_status_code=403)
        with pytest.raises(ClientError) as excinfo:
            solution.stop_instances(client, ["i-0123456789abcdef0"], dry_run=True)
    assert excinfo.value.response["Error"]["Code"] == "UnauthorizedOperation"


def test_stop_instances_bad_id_raises(solution, ec2):
    with pytest.raises(ClientError):
        solution.stop_instances(ec2, ["i-0123456789abcdef0"], dry_run=False)
