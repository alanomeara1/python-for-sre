from collections import namedtuple

import pytest

Usage = namedtuple("Usage", "total used free")


def fake_disk(monkeypatch, solution, percent, seen=None):
    def disk_usage(path):
        if seen is not None:
            seen.append(path)
        return Usage(total=1000, used=int(percent * 10), free=1000 - int(percent * 10))

    monkeypatch.setattr(solution.shutil, "disk_usage", disk_usage)


def test_evaluate_levels_and_boundaries(solution):
    assert solution.evaluate(50.0, 80, 90) == (0, "OK")
    assert solution.evaluate(80.0, 80, 90) == (1, "WARNING")
    assert solution.evaluate(89.9, 80, 90) == (1, "WARNING")
    assert solution.evaluate(90.0, 80, 90) == (2, "CRITICAL")
    assert solution.evaluate(100.0, 80, 90) == (2, "CRITICAL")


def test_parser_defaults(solution):
    args = solution.build_parser().parse_args([])
    assert args.path == "/"
    assert args.warn == 80.0 and args.crit == 90.0
    assert args.verbose is False


def test_parser_short_flags_and_types(solution):
    args = solution.build_parser().parse_args(["--path", "/var", "-w", "70", "-c", "85", "-v"])
    assert args.path == "/var"
    assert args.warn == 70.0 and isinstance(args.warn, float)
    assert args.crit == 85.0 and isinstance(args.crit, float)
    assert args.verbose is True


def test_main_ok(solution, monkeypatch, capsys):
    fake_disk(monkeypatch, solution, 50)
    assert solution.main([]) == 0
    assert capsys.readouterr().out == "DISK OK - / 50.0% used\n"


def test_main_warning(solution, monkeypatch, capsys):
    fake_disk(monkeypatch, solution, 85)
    assert solution.main(["--warn", "80", "--crit", "90"]) == 1
    assert capsys.readouterr().out == "DISK WARNING - / 85.0% used\n"


def test_main_critical_checks_the_given_path(solution, monkeypatch, capsys):
    seen = []
    fake_disk(monkeypatch, solution, 95, seen)
    assert solution.main(["--path", "/data"]) == 2
    assert seen == ["/data"]
    assert capsys.readouterr().out == "DISK CRITICAL - /data 95.0% used\n"


def test_main_rejects_warn_not_below_crit(solution, monkeypatch, capsys):
    fake_disk(monkeypatch, solution, 50)
    with pytest.raises(SystemExit) as exc:
        solution.main(["-w", "90", "-c", "80"])
    assert exc.value.code == 2
    assert "--warn" in capsys.readouterr().err


def test_main_unknown_when_disk_unreadable(solution, monkeypatch, capsys):
    def boom(path):
        raise FileNotFoundError(2, "No such file or directory", path)

    monkeypatch.setattr(solution.shutil, "disk_usage", boom)
    assert solution.main(["--path", "/nope"]) == 3
    assert capsys.readouterr().out.startswith("DISK UNKNOWN - /nope")


def test_status_line_is_the_only_stdout(solution, monkeypatch, capsys):
    fake_disk(monkeypatch, solution, 50)
    solution.main(["-v"])
    assert capsys.readouterr().out.count("\n") == 1
