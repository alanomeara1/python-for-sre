"""EC2 hygiene: unattached EBS volumes, missing mandatory tags, safe instance stop."""

from botocore.exceptions import ClientError


def find_unattached_volumes(ec2) -> list[dict]:
    volumes = []
    paginator = ec2.get_paginator("describe_volumes")    # one call returns only one page
    # Filter server-side: fewer bytes and fewer API calls than filtering in Python.
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page["Volumes"]:
            volumes.append({
                "id": volume["VolumeId"],
                "size": volume["Size"],
                "created": volume["CreateTime"],
            })
    return sorted(volumes, key=lambda v: (v["created"], v["id"]))


def find_instances_missing_tags(ec2, required: set[str]) -> dict[str, list[str]]:
    missing = {}
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:          # instances are nested in reservations
            for instance in reservation["Instances"]:
                if instance["State"]["Name"] in ("terminated", "shutting-down"):
                    continue
                # The "Tags" key is absent, not [], on an untagged instance.
                present = {tag["Key"] for tag in instance.get("Tags", [])}
                if absent := required - present:
                    missing[instance["InstanceId"]] = sorted(absent)
    return missing


def stop_instances(ec2, instance_ids: list[str], dry_run: bool = True) -> list[str]:
    if not instance_ids:
        # Never send an empty id list: on describe_* calls it means "all instances".
        return []
    try:
        response = ec2.stop_instances(InstanceIds=instance_ids, DryRun=dry_run)
    except ClientError as e:
        # A dry run that WOULD succeed is reported as this error code.
        if dry_run and e.response["Error"]["Code"] == "DryRunOperation":
            return list(instance_ids)
        raise                                               # UnauthorizedOperation etc. must surface
    return [item["InstanceId"] for item in response["StoppingInstances"]]


if __name__ == "__main__":
    import boto3

    client = boto3.client("ec2")
    print("region:", client.meta.region_name)
    for vol in find_unattached_volumes(client):
        print(vol["id"], f'{vol["size"]} GiB', "created", vol["created"].isoformat())
