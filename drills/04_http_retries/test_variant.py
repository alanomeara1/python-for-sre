import pytest


def test_retries_then_succeeds(variant):
    sleeps, calls = [], []

    @variant.retry(exceptions=(ConnectionError,), attempts=3, base_delay=0.1, sleep=sleeps.append)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("blip")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]
    assert flaky.last_attempts == 3


def test_reraises_last_original_exception(variant):
    sleeps, calls = [], []

    @variant.retry(exceptions=(ConnectionError,), attempts=3, base_delay=0.1, sleep=sleeps.append)
    def always_down():
        calls.append(1)
        raise ConnectionError(f"boom {len(calls)}")

    with pytest.raises(ConnectionError, match="boom 3"):
        always_down()
    assert sleeps == [0.1, 0.2]
    assert always_down.last_attempts == 3


def test_unlisted_exception_is_not_retried(variant):
    sleeps, calls = [], []

    @variant.retry(exceptions=(ConnectionError,), attempts=5, sleep=sleeps.append)
    def buggy():
        calls.append(1)
        raise ValueError("my bug")

    with pytest.raises(ValueError, match="my bug"):
        buggy()
    assert len(calls) == 1
    assert sleeps == []


def test_delay_is_capped(variant):
    sleeps = []

    @variant.retry(exceptions=(TimeoutError,), attempts=6, base_delay=1.0, max_delay=4.0, sleep=sleeps.append)
    def slow():
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        slow()
    assert sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]


def test_wraps_preserves_metadata_and_passes_arguments(variant):
    @variant.retry(sleep=lambda s: None)
    def get_leader(cluster, *, region="eu-west-1"):
        """Return the current leader node."""
        return f"{cluster}/{region}"

    assert get_leader.__name__ == "get_leader"
    assert get_leader.__doc__ == "Return the current leader node."
    assert get_leader("etcd", region="us-east-1") == "etcd/us-east-1"
    assert get_leader.last_attempts == 1


def test_invalid_attempts_rejected_at_decoration_time(variant):
    with pytest.raises(ValueError):
        variant.retry(attempts=0)
