"""EC2 hygiene: unattached EBS volumes, missing mandatory tags, safe instance stop.

The client is a PARAMETER, never built inside: that makes these testable against moto
or a Stubber, lets the caller own region/profile/retry config, and reuses one client
(building one parses big JSON service models). Full reasoning in EXPLAINED.md.
"""

from botocore.exceptions import ClientError


def find_unattached_volumes(ec2) -> list[dict]:
    volumes = []
    # Paginate, always. describe_* calls are capped (~1000 results) and return a NextToken;
    # ignore it and you silently audit a FRACTION of the account. The cruelty is that it works
    # perfectly in a small sandbox and under-reports in production, where people trust it.
    paginator = ec2.get_paginator("describe_volumes")    # one call returns only one page
    # Filter server-side: fewer bytes and fewer API calls than filtering in Python.
    # Filters syntax is the same across EC2: a list of {"Name", "Values"}, Values always a list.
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page["Volumes"]:
            # Return small dicts of our own, not raw AWS responses: the caller and the tests
            # stay clear of thirty irrelevant keys, and an API shape change lands in one place.
            volumes.append({
                "id": volume["VolumeId"],
                "size": volume["Size"],
                "created": volume["CreateTime"],
            })
    # Oldest waste first, which is what finance asked for; the id tie-break keeps it deterministic.
    return sorted(volumes, key=lambda v: (v["created"], v["id"]))


def find_instances_missing_tags(ec2, required: set[str]) -> dict[str, list[str]]:
    missing = {}
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:          # instances are nested in reservations
            # A reservation is ONE RunInstances call, so ten instances launched together arrive
            # as one reservation containing ten. Historical API shape; you just unwrap it.
            for instance in reservation["Instances"]:
                # A terminated instance costs nothing and cannot be tagged, so reporting it is
                # noise -- and a compliance report full of noise is one nobody reads.
                if instance["State"]["Name"] in ("terminated", "shutting-down"):
                    continue
                # The "Tags" key is absent, not [], on an untagged instance.
                # instance["Tags"] would raise KeyError on exactly the instances you are hunting.
                # Tags arrive as a LIST of {"Key","Value"} dicts, not a mapping.
                present = {tag["Key"] for tag in instance.get("Tags", [])}
                # Set difference is the whole question in one expression. The walrus computes it
                # once and skips compliant instances, because an empty set is falsy.
                if absent := required - present:
                    missing[instance["InstanceId"]] = sorted(absent)
    return missing


def stop_instances(ec2, instance_ids: list[str], dry_run: bool = True) -> list[str]:
    # dry_run defaults to True because this function stops production. Someone calling it in a
    # hurry gets a no-op, not an outage; pair it with an explicit --apply flag at the CLI layer.
    if not instance_ids:
        # Never send an empty id list: on describe_* calls it means "all instances".
        # It also avoids a pointless API call -- the test queues no response, so any call raises.
        return []
    try:
        response = ec2.stop_instances(InstanceIds=instance_ids, DryRun=dry_run)
    except ClientError as e:
        # A dry run that WOULD succeed is reported as this error code.
        # Counter-intuitive but true: with DryRun there is no success response to inspect, so the
        # happy path lives in the except block.
        if dry_run and e.response["Error"]["Code"] == "DryRunOperation":
            return list(instance_ids)
        # `except ClientError: pass` would swallow UnauthorizedOperation and report "would
        # succeed" -- turning the safety check into a lie you discover mid-way through the real
        # run. Bare `raise` re-raises with the original traceback intact.
        raise                                               # UnauthorizedOperation etc. must surface
    # Read the ids back from the response rather than echoing the input: AWS tells you what it
    # actually acted on.
    return [item["InstanceId"] for item in response["StoppingInstances"]]


if __name__ == "__main__":
    import boto3

    client = boto3.client("ec2")
    # Print the region: a script run against the wrong one finds nothing and looks beautifully clean.
    print("region:", client.meta.region_name)
    for vol in find_unattached_volumes(client):
        print(vol["id"], f'{vol["size"]} GiB', "created", vol["created"].isoformat())
