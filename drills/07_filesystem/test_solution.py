import os

import pytest

NOW = 1_800_000_000.0     # fixed "current time" in epoch seconds
DAY = 86_400


def make(path, days_old, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    mtime = NOW - days_old * DAY
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def logs(tmp_path):
    root = tmp_path / "logs"
    make(root / "app.log", 0, size=100)
    make(root / "app.log.1", 3, size=200)
    make(root / "app.log.2", 10, size=300)
    make(root / "nested" / "worker.log", 20, size=5000)
    make(root / "nested" / "deep" / "core.dump", 40, size=9000)
    return root


def test_find_files_age_recursive_sorted(solution, logs):
    found = solution.find_files(logs, older_than_days=7, now=NOW)
    assert found == sorted([logs / "app.log.2", logs / "nested" / "deep" / "core.dump",
                            logs / "nested" / "worker.log"])


def test_find_files_min_bytes_and_pattern(solution, logs):
    assert solution.find_files(logs, 7, min_bytes=1000, now=NOW) == sorted(
        [logs / "nested" / "deep" / "core.dump", logs / "nested" / "worker.log"])
    assert solution.find_files(logs, 1, pattern="*.log*", now=NOW) == sorted(
        [logs / "app.log.1", logs / "app.log.2", logs / "nested" / "worker.log"])


def test_find_files_skips_symlinks(solution, logs, tmp_path):
    outside = tmp_path / "precious"
    make(outside / "database.db", 100, size=50)
    (logs / "link-to-dir").symlink_to(outside, target_is_directory=True)
    (logs / "link-to-file.log").symlink_to(outside / "database.db")

    found = solution.find_files(logs, 7, now=NOW)
    assert all("precious" not in str(p) and "link" not in p.name for p in found)
    assert len(found) == 3


def test_find_files_default_now_uses_real_clock(solution, tmp_path):
    (tmp_path / "fresh.log").write_text("written just now")
    old = tmp_path / "old.log"
    old.write_text("from 2001")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    assert solution.find_files(tmp_path, 1) == [old]


def test_cleanup_dry_run_deletes_nothing(solution, logs):
    report = solution.cleanup(logs, 7, now=NOW)
    assert report["deleted"] is False
    assert report["bytes"] == 300 + 5000 + 9000
    assert len(report["files"]) == 3
    assert all(p.exists() for p in report["files"])


def test_cleanup_for_real(solution, logs, tmp_path):
    outside = tmp_path / "precious"
    make(outside / "database.db", 100)
    (logs / "link-to-dir").symlink_to(outside, target_is_directory=True)

    report = solution.cleanup(logs, 7, dry_run=False, now=NOW)
    assert report["deleted"] is True
    assert report["bytes"] == 14300
    assert not any(p.exists() for p in report["files"])
    assert (logs / "app.log").exists() and (logs / "app.log.1").exists()
    assert (outside / "database.db").exists()


def test_rotate_keeps_newest(solution, tmp_path):
    for i in range(1, 6):
        make(tmp_path / f"backup-{i}.tar", days_old=i)
    make(tmp_path / "notes.txt", days_old=99)

    removed = solution.rotate(tmp_path, "backup-*.tar", keep=2)
    assert removed == [tmp_path / "backup-3.tar", tmp_path / "backup-4.tar", tmp_path / "backup-5.tar"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["backup-1.tar", "backup-2.tar", "notes.txt"]


def test_rotate_edge_cases(solution, tmp_path):
    for i in range(1, 3):
        make(tmp_path / f"b{i}.gz", days_old=i)
    assert solution.rotate(tmp_path, "*.gz", keep=10) == []
    assert solution.rotate(tmp_path, "*.gz", keep=0) == [tmp_path / "b1.gz", tmp_path / "b2.gz"]
    with pytest.raises(ValueError):
        solution.rotate(tmp_path, "*.gz", keep=-1)
