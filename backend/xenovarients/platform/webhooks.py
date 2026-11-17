"""Webhook signature verification.

Every inbound webhook is authenticated before it is parsed. Three properties matter,
and each one has been a real vulnerability in real webhook systems:

1. **Constant-time comparison.** ``hmac.compare_digest`` — a byte-by-byte ``==``
   leaks the signature through timing.
2. **A timestamp window.** A captured signature is valid forever otherwise, so a
   replay window bounds the damage. The default is 300 seconds.
3. **The raw body, not the parsed JSON.** Providers sign the bytes they sent. If the
   framework re-serialises the parsed body, the signature no longer matches — and if
   the implementation signs the *parsed* body, an attacker can reorder keys.

The provider adapters translate their own signature scheme into this one common shape.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass

from xenovarients.core.config import get_settings


class SignatureError(Exception):
    """Raised when a webhook signature does not verify."""


@dataclass(frozen=True)
class WebhookSignature:
    """A verified webhook signature."""

    timestamp: int
    signature: str


def verify_hmac_sha256(
    *,
    body: bytes,
    signature: str,
    secret: str,
    timestamp: int | None = None,
    tolerance_seconds: int | None = None,
) -> WebhookSignature:
    """Verify a ``sha256=<hex>`` HMAC signature over ``body``.

    The signed payload is ``{timestamp}.{body}`` — the standard scheme, which binds
    the signature to a moment in time so a captured request cannot be replayed later.
    """
    settings = get_settings()
    tolerance = (
        tolerance_seconds
        if tolerance_seconds is not None
        else settings.webhook_timestamp_tolerance_seconds
    )

    if timestamp is None:
        raise SignatureError("Webhook is missing its timestamp.")

    now = int(time.time())
    if abs(now - timestamp) > tolerance:
        raise SignatureError("Webhook timestamp is outside the accepted window.")

    if not signature.startswith("sha256="):
        raise SignatureError("Webhook signature must use the sha256= prefix.")

    provided = signature.removeprefix("sha256=")
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body.decode('utf-8', errors='replace')}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, provided):
        raise SignatureError("Webhook signature does not match.")

    return WebhookSignature(timestamp=timestamp, signature=provided)


def verify_meta_signature(*, body: bytes, signature: str, secret: str) -> None:
    """Verify Meta's webhook signature.

    Meta sends ``X-Hub-Signature-256: sha256=<hex>`` and signs the raw body with the
    app secret — no timestamp is bound into the payload, so there is no built-in
    replay window. The timestamp is checked separately by the caller if the provider
    sends one; for Meta, the dedupe on ``provider_event_id`` is what stops a replay
    from having any effect.
    """
    if not signature.startswith("sha256="):
        raise SignatureError("Webhook signature must use the sha256= prefix.")
    provided = signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise SignatureError("Webhook signature does not match.")
