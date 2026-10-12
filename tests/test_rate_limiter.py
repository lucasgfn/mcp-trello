import pytest

from trello_org_mcp.trello.rate_limiter import TokenBucket


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_allows_burst_up_to_capacity_then_waits() -> None:
    t = FakeTime()
    bucket = TokenBucket(3, 10.0, clock=t.clock, sleep=t.sleep)
    for _ in range(3):
        await bucket.acquire()
    assert t.sleeps == []
    await bucket.acquire()
    assert t.sleeps == [pytest.approx(10 / 3)]


async def test_refills_over_time() -> None:
    t = FakeTime()
    bucket = TokenBucket(2, 10.0, clock=t.clock, sleep=t.sleep)
    await bucket.acquire()
    await bucket.acquire()
    t.now += 10
    await bucket.acquire()
    await bucket.acquire()
    assert t.sleeps == []


def test_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        TokenBucket(0)
