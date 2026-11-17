"""Per-channel outbound rate limits.

The limiter paces a burst so the provider does not throttle it. Two properties
matter and are pinned here: the limit is per business (one tenant's burst must not
consume another's budget), and a limiter that cannot answer fails *open* (a Redis
outage must not stop all messaging).
"""

import uuid
from typing import Any

import pytest

from xenovarients.platform.ratelimit import (
    DEFAULT_CHANNEL_LIMITS,
    check,
    limit_for,
)


class FakeRedis:
    """A Redis stand-in that counts and expires, like the real thing."""

    def __init__(self, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.fail = fail

    async def incr(self, key: str) -> int:
        if self.fail:
            raise RuntimeError("Redis is down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True


@pytest.mark.asyncio
async def test_sends_are_allowed_up_to_the_limit() -> None:
    redis = FakeRedis()
    business_id = uuid.uuid4()
    ceiling = limit_for("sms")

    for index in range(ceiling):
        decision = await check(redis, business_id=business_id, channel="sms")
        assert decision.allowed is True, f"send {index + 1} was blocked"
        assert decision.remaining == ceiling - index - 1


@pytest.mark.asyncio
async def test_the_send_after_the_limit_is_deferred() -> None:
    redis = FakeRedis()
    business_id = uuid.uuid4()
    ceiling = limit_for("sms")

    for _ in range(ceiling):
        await check(redis, business_id=business_id, channel="sms")

    decision = await check(redis, business_id=business_id, channel="sms")
    assert decision.allowed is False
    assert decision.remaining == 0
    assert decision.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_each_business_has_its_own_budget() -> None:
    """One tenant's burst must not consume another's budget."""
    redis = FakeRedis()
    ceiling = limit_for("sms")

    noisy = uuid.uuid4()
    quiet = uuid.uuid4()
    for _ in range(ceiling):
        await check(redis, business_id=noisy, channel="sms")

    assert (await check(redis, business_id=noisy, channel="sms")).allowed is False
    assert (await check(redis, business_id=quiet, channel="sms")).allowed is True


@pytest.mark.asyncio
async def test_each_channel_has_its_own_budget() -> None:
    """An SMS burst must not block email."""
    redis = FakeRedis()
    business_id = uuid.uuid4()
    ceiling = limit_for("sms")

    for _ in range(ceiling):
        await check(redis, business_id=business_id, channel="sms")

    assert (await check(redis, business_id=business_id, channel="sms")).allowed is False
    assert (await check(redis, business_id=business_id, channel="email")).allowed is True


@pytest.mark.asyncio
async def test_the_counter_expires_with_the_window() -> None:
    """The window must reset, or a busy tenant would be blocked forever."""
    redis = FakeRedis()
    business_id = uuid.uuid4()

    await check(redis, business_id=business_id, channel="sms")
    assert redis.expiries, "the counter was never given an expiry"


@pytest.mark.asyncio
async def test_a_redis_failure_fails_open() -> None:
    """A limiter outage must not stop sends — the provider's throttle is worse."""
    redis = FakeRedis(fail=True)
    decision = await check(redis, business_id=uuid.uuid4(), channel="sms")
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_the_window_key_is_scoped_by_business_and_channel() -> None:
    redis = FakeRedis()
    await check(redis, business_id=uuid.uuid4(), channel="sms")
    await check(redis, business_id=uuid.uuid4(), channel="email")
    assert len(redis.counts) == 2


def test_every_channel_has_a_limit() -> None:
    """A channel without a limit would default to something arbitrary."""
    for channel in ("email", "sms", "messenger", "whatsapp"):
        assert channel in DEFAULT_CHANNEL_LIMITS
        assert limit_for(channel) > 0


def test_the_limit_can_be_overridden_by_settings(monkeypatch: Any) -> None:
    from xenovarients.core import config
    from xenovarients.platform import ratelimit

    monkeypatch.setattr(
        ratelimit,
        "get_settings",
        lambda: config.Settings(jwt_secret="x" * 40, rate_limit_sms=5),
    )
    assert limit_for("sms") == 5


def test_a_zero_override_uses_the_default(monkeypatch: Any) -> None:
    from xenovarients.core import config
    from xenovarients.platform import ratelimit

    monkeypatch.setattr(ratelimit, "get_settings", lambda: config.Settings(jwt_secret="x" * 40))
    assert limit_for("sms") == DEFAULT_CHANNEL_LIMITS["sms"]
