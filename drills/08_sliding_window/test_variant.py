def test_starts_full_then_empties(variant):
    b = variant.TokenBucket(rate_per_sec=2, capacity=4)
    assert [b.allow(now=0) for _ in range(5)] == [True, True, True, True, False]


def test_lazy_refill(variant):
    b = variant.TokenBucket(rate_per_sec=2, capacity=4)
    for _ in range(4):
        b.allow(now=0)
    assert b.allow(now=0.25) is False        # 0.5 tokens
    assert b.allow(now=0.5) is True          # 1.0 token
    assert b.allow(now=0.5) is False


def test_refill_is_capped_at_capacity(variant):
    b = variant.TokenBucket(rate_per_sec=2, capacity=4)
    for _ in range(4):
        b.allow(now=0)
    assert [b.allow(now=1000) for _ in range(5)] == [True, True, True, True, False]


def test_cost(variant):
    b = variant.TokenBucket(rate_per_sec=1, capacity=5)
    assert b.allow(now=0, cost=3) is True
    assert b.allow(now=0, cost=3) is False   # 2 left, rejection consumes nothing
    assert b.allow(now=0, cost=2) is True
    assert b.allow(now=100, cost=6) is False  # more than capacity: never


def test_clock_going_backwards_grants_nothing(variant):
    b = variant.TokenBucket(rate_per_sec=2, capacity=2)
    assert b.allow(now=10) and b.allow(now=10)
    assert b.allow(now=5) is False           # jumped back: no tokens
    assert b.allow(now=10.5) is True         # exactly 1 token for 10 -> 10.5
    assert b.allow(now=10.5) is False        # NOT a second token for 5 -> 10.5


def test_clock_going_backwards_takes_nothing_away(variant):
    b = variant.TokenBucket(rate_per_sec=2, capacity=2)
    assert b.allow(now=10) is True           # 1 token left
    assert b.allow(now=5) is True            # negative elapsed must not drain the bucket
    assert b.allow(now=5) is False


def test_keyed_limiter_independent_buckets(variant):
    kl = variant.KeyedLimiter(rate_per_sec=1, capacity=2)
    assert kl.allow("alice", 0) and kl.allow("alice", 0)
    assert kl.allow("alice", 0) is False
    assert kl.allow("bob", 0) is True        # bob gets a separate, full bucket
    assert kl.allow("carol", 50, cost=2) is True
    assert kl.allow("alice", 1) is True      # alice refilled 1 token
