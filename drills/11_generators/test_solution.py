import inspect
import itertools

import pytest

LOG = """\
{"level": "info", "msg": "started"}
{"level": "error", "msg": "db timeout"}
not json at all

[1, 2, 3]
{"level": "error", "msg": "db timeout again"}
  {"level": "info", "msg": "indented"}
"""


def test_read_lines_strips_newline_only(solution, tmp_path):
    path = tmp_path / "app.log"
    path.write_text(LOG)
    lines = list(solution.read_lines(path))
    assert lines[0] == '{"level": "info", "msg": "started"}'
    assert lines[3] == ""
    assert lines[-1] == '  {"level": "info", "msg": "indented"}'
    assert len(lines) == 7


def test_read_lines_is_lazy(solution, tmp_path):
    path = tmp_path / "app.log"
    path.write_text(LOG)
    assert inspect.isgenerator(solution.read_lines(path))


def test_grep(solution):
    lines = ["GET /a 200", "GET /b 500", "POST /c 503"]
    assert list(solution.grep(r" 5\d\d$", lines)) == ["GET /b 500", "POST /c 503"]


def test_grep_is_lazy_on_infinite_input(solution):
    endless = itertools.cycle(["noise", "ERROR boom"])
    assert next(solution.grep("ERROR", endless)) == "ERROR boom"


def test_parse_json_lines_skips_and_reports_bad_lines(solution):
    errors = []
    records = list(solution.parse_json_lines(LOG.splitlines(), errors=errors))
    assert [r["msg"] for r in records] == ["started", "db timeout", "db timeout again", "indented"]
    assert errors == [(3, "not json at all"), (5, "[1, 2, 3]")]


def test_parse_json_lines_without_errors_list(solution):
    assert len(list(solution.parse_json_lines(["{bad", '{"ok": 1}']))) == 1


def test_pipeline_end_to_end(solution, tmp_path):
    path = tmp_path / "app.log"
    path.write_text(LOG)
    records = solution.parse_json_lines(solution.grep('"error"', solution.read_lines(path)))
    assert [r["msg"] for r in records] == ["db timeout", "db timeout again"]


def test_batched(solution):
    assert list(solution.batched(range(7), 3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(solution.batched([], 3)) == []
    assert list(solution.batched([1, 2], 5)) == [[1, 2]]


def test_batched_works_on_a_list_and_infinite_iterator(solution):
    assert list(solution.batched([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]
    assert next(solution.batched(itertools.count(), 4)) == [0, 1, 2, 3]


def test_batched_rejects_bad_n(solution):
    with pytest.raises(ValueError):
        list(solution.batched([1], 0))


def test_follow_starts_at_end_and_joins_partial_lines(solution, tmp_path):
    path = tmp_path / "app.log"
    path.write_text("old line that must not appear\n")
    writes = iter(["new 1\nnew 2\n", "partial", " done\n"])

    def fake_sleep(_seconds):
        chunk = next(writes, None)
        if chunk is not None:
            with open(path, "a") as f:
                f.write(chunk)

    out = list(solution.follow(path, poll_interval=0, max_idle_polls=2, sleep=fake_sleep))
    assert out == ["new 1", "new 2", "partial done"]


def test_follow_gives_up_after_max_idle_polls(solution, tmp_path):
    path = tmp_path / "app.log"
    path.write_text("x\n")
    sleeps = []
    out = list(solution.follow(path, poll_interval=0.5, max_idle_polls=3, sleep=sleeps.append))
    assert out == []
    assert sleeps == [0.5, 0.5, 0.5]
