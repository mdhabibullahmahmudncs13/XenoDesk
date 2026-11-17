"""Per-channel outbound rate limits.

A provider will throttle a sender that sends too fast, and the provider's own
throttle is worse than ours: it fails the sends. This limiter keeps the send rate
under the provider's ceiling so a burst is paced rather than rejected.

**The limit is per business per channel.** One tenant's burst must not consume
another tenant's budget — the provider's quota is usually shared, but the *fairness*
rule is per tenant, and a noisy tenant must not starve a quiet one.

**A limiter that cannot answer does not block.** If Redis is unavailable the
limiter fails open: the sends go out and the provider's own throttle handles the
overflow. Failing closed would mean a Redis outage stops all messaging, which is
a worse outcome than a few throttled sends.
"""

import logging
import uuid
from dataclasses import dataclass

from xenovarients.core.config import get_settings

logger = logging.getLogger(__name__)

# The Redis key for one business's channel window.
KEY_TEMPLATE = "xenovarients:ratelimit:{business_id}:{channel}:{window}"

# The window length in seconds.
WINDOW_SECONDS = 60

# The per-channel send ceiling per business per window.
#
# These are the provider's published tiers for the smallest plan, and are the
# conservative choice: a business on a bigger plan is limited more than it needs
# to be, which costs throughput but never a throttled send. They are settings, not
# constants, because the tiers are per provider and change.
DEFAULT_CHANNEL_LIMITS: dict[str, int] = {
    "email": 60,
    "sms": 30,
    "messenger": 20,
    "whatsapp": 20,
}


@dataclass(frozen=True)
class RateLimitDecision:
    """Whether a send may proceed, and how long to wait if not."""

    allowed: bool
    remaining: int
    retry_after_seconds: int

    @classmethod
    def allow(cls, remaining: int) -> "RateLimitDecision":
        return cls(allowed=True, remaining=remaining, retry_after_seconds=0)


def limit_for(channel: str) -> int:
    """The per-window ceiling for a channel."""
    settings = get_settings()
    override = getattr(settings, f"rate_limit_{channel}", None)
    if isinstance(override, int) and override > 0:
        return override
    return DEFAULT_CHANNEL_LIMITS.get(channel, 30)


async def check(redis: object, *, business_id: uuid.UUID | str, channel: str) -> RateLimitDecision:
    """Whether one more send may go out on this channel right now.

    Uses a fixed window: the counter is keyed by the window's start, so it resets
    on the window boundary rather than sliding. That is what providers publish
    their limits against, and a sliding window needs more state than the accuracy
    is worth here.
    """
    ceiling = limit_for(channel)
    window = _current_window()
    key = KEY_TEMPLATE.format(business_id=business_id, channel=channel, window=window)

    try:
        count = await redis.incr(key)  # type: ignore[attr-defined]
        if count == 1:
            await redis.expire(key, WINDOW_SECONDS)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — a limiter outage must not stop sends
        logger.warning("Rate limit check failed, allowing the send: %s", exc)
        return RateLimitDecision(allowed=True, remaining=ceiling, retry_after_seconds=0)

    if count <= ceiling:
        return RateLimitDecision.allow(ceiling - int(count))

    return RateLimitDecision(
        allowed=False,
        remaining=0,
        retry_after_seconds=_seconds_until_next_window(),
    )


def _current_window() -> int:
    """The current window's index."""
    import time

    return int(time.time() // WINDOW_SECONDS)


def _seconds_until_next_window() -> int:
    """How long until the window resets."""
    import time

    remaining = WINDOW_SECONDS - (int(time.time()) % WINDOW_SECONDS)
    return max(1, remaining)
