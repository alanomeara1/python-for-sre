import json
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)


def write_inventory(tmp_path, data):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_days_left_rounds_down_and_goes_negative(variant):
    assert variant.days_left(datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc), NOW) == 3
    assert variant.days_left(datetime(2026, 9, 17, 23, 59, tzinfo=timezone.utc), NOW) == 0
    assert variant.days_left(datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc), NOW) == -2


def test_status_for_boundaries(variant):
    assert variant.status_for(31, 30, 7) == 0
    assert variant.status_for(30, 30, 7) == 1
    assert variant.status_for(8, 30, 7) == 1
    assert variant.status_for(7, 30, 7) == 2
    assert variant.status_for(-5, 30, 7) == 2


def test_parser_defaults(variant):
    args = variant.build_parser().parse_args(["inv.json"])
    assert args.inventory == "inv.json"
    assert args.warn_days == 30 and args.crit_days == 7


def test_main_sorted_output_and_worst_exit(variant, tmp_path, capsys):
    inv = write_inventory(tmp_path, {
        "zeta.example.com": "2027-01-01T00:00:00+00:00",
        "api.example.com": "2026-10-01T00:00:00+00:00",
        "db.internal": "2026-09-20T12:00:00+00:00",
    })
    assert variant.main([inv], now=NOW) == 2
    assert capsys.readouterr().out.splitlines() == [
        "CRITICAL db.internal 3 days left",
        "WARNING api.example.com 14 days left",
        "OK zeta.example.com 106 days left",
    ]


def test_main_ties_sorted_by_host(variant, tmp_path, capsys):
    inv = write_inventory(tmp_path, {
        "b.example.com": "2027-01-01T00:00:00+00:00",
        "a.example.com": "2027-01-01T00:00:00+00:00",
    })
    assert variant.main([inv], now=NOW) == 0
    assert [line.split()[1] for line in capsys.readouterr().out.splitlines()] == ["a.example.com", "b.example.com"]


def test_main_custom_thresholds(variant, tmp_path, capsys):
    inv = write_inventory(tmp_path, {"api.example.com": "2026-10-01T00:00:00+00:00"})
    assert variant.main([inv, "--warn-days", "10", "--crit-days", "3"], now=NOW) == 0


def test_main_empty_inventory_is_ok(variant, tmp_path):
    assert variant.main([write_inventory(tmp_path, {})], now=NOW) == 0


def test_main_unreadable_inventory_is_unknown(variant, tmp_path, capsys):
    assert variant.main([str(tmp_path / "missing.json")], now=NOW) == 3
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert variant.main([str(bad)], now=NOW) == 3
    assert capsys.readouterr().out.startswith("UNKNOWN - cannot read inventory")


def test_main_rejects_crit_not_below_warn(variant, tmp_path):
    inv = write_inventory(tmp_path, {})
    with pytest.raises(SystemExit) as exc:
        variant.main([inv, "--warn-days", "7", "--crit-days", "7"], now=NOW)
    assert exc.value.code == 2
