import sys

PY = sys.executable

DF = """\
Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/sda1         10255636   9230072    512000      95% /
map auto_home            0         0         0     100% /System/Volumes/Data/home
/dev/sdb1        103081248  61848748  36000000      64% /mnt/my data
tmpfs              4000000   3400000    600000      85% /run

overlay                  0         0         0        - /var/lib/docker/overlay
"""


def test_run_command_captures_text_output(solution):
    r = solution.run_command([PY, "-c", "import sys; print('hello'); print('oops', file=sys.stderr)"], timeout=10)
    assert r.returncode == 0
    assert r.stdout == "hello\n"
    assert r.stderr == "oops\n"
    assert r.timed_out is False
    assert r.ok is True
    assert isinstance(r.duration, float) and r.duration > 0


def test_run_command_nonzero_exit_does_not_raise(solution):
    r = solution.run_command([PY, "-c", "import sys; sys.exit(3)"], timeout=10)
    assert r.returncode == 3
    assert r.ok is False


def test_run_command_timeout(solution):
    r = solution.run_command([PY, "-c", "import time; time.sleep(10)"], timeout=0.5)
    assert r.timed_out is True
    assert r.returncode == 124
    assert r.ok is False
    assert r.duration < 5


def test_run_command_missing_binary(solution):
    r = solution.run_command(["definitely-not-a-real-binary-xyz"], timeout=5)
    assert r.returncode == 127
    assert "definitely-not-a-real-binary-xyz" in r.stderr
    assert r.ok is False


def test_run_command_does_not_use_a_shell(solution):
    nasty = "$HOME; echo pwned"
    r = solution.run_command([PY, "-c", "import sys; print(sys.argv[1])", nasty], timeout=10)
    assert r.stdout == nasty + "\n"


def test_parse_df_rows_types_and_spaces(solution):
    rows = solution.parse_df(DF)
    assert len(rows) == 5
    assert rows[0] == {"filesystem": "/dev/sda1", "size_kb": 10255636, "used_kb": 9230072,
                       "available_kb": 512000, "use_percent": 95, "mount": "/"}
    assert rows[1]["filesystem"] == "map auto_home"
    assert rows[2]["mount"] == "/mnt/my data"
    assert rows[4]["use_percent"] == 0


def test_parse_df_empty(solution):
    assert solution.parse_df("") == []


def test_filesystems_over_filters_sorts_and_skips_pseudo(solution):
    over = solution.filesystems_over(DF, 80)
    assert [fs["mount"] for fs in over] == ["/", "/run"]


def test_filesystems_over_threshold_is_inclusive(solution):
    assert [fs["mount"] for fs in solution.filesystems_over(DF, 85)] == ["/", "/run"]
    assert [fs["mount"] for fs in solution.filesystems_over(DF, 96)] == []
