import json


def rc(address, actions):
    return {"address": address, "type": address.split(".")[0], "change": {"actions": actions}}


PLAN = {
    "format_version": "1.2",
    "resource_changes": [
        rc("aws_db_instance.main", ["delete", "create"]),
        rc("aws_instance.web[0]", ["update"]),
        rc("aws_instance.web[1]", ["update"]),
        rc("aws_s3_bucket.logs", ["no-op"]),
        rc("aws_s3_bucket.assets", ["create", "delete"]),
        rc("aws_security_group.web", ["create"]),
        rc("aws_db_instance.replica", ["delete"]),
        rc("aws_iam_role.old", ["delete"]),
        rc("data_source.ami", ["read"]),
    ],
}


def test_classify(variant):
    assert variant.classify(["create"]) == "create"
    assert variant.classify(["update"]) == "update"
    assert variant.classify(["delete"]) == "delete"
    assert variant.classify(["delete", "create"]) == "replace"
    assert variant.classify(["create", "delete"]) == "replace"
    assert variant.classify(["no-op"]) is None
    assert variant.classify(["read"]) is None


def test_summarize_plan(variant):
    assert variant.summarize_plan(PLAN) == {"create": 1, "update": 2, "delete": 2, "replace": 2}


def test_summarize_empty_plan_has_all_keys(variant):
    assert variant.summarize_plan({"format_version": "1.2"}) == {
        "create": 0, "update": 0, "delete": 0, "replace": 0}


def test_dangerous_changes(variant):
    protected = {"aws_db_instance", "aws_s3_bucket"}
    assert variant.dangerous_changes(PLAN, protected) == [
        "aws_db_instance.main",
        "aws_db_instance.replica",
        "aws_s3_bucket.assets",
    ]


def test_dangerous_changes_ignores_unprotected_and_safe(variant):
    assert variant.dangerous_changes(PLAN, {"aws_instance", "aws_security_group"}) == []
    assert variant.dangerous_changes({}, {"aws_db_instance"}) == []


def test_load_plan(variant, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN))
    assert variant.summarize_plan(variant.load_plan(path))["replace"] == 2
