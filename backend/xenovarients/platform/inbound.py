"""Inbound messaging: provider adapters and the event ingest path.

The contract with every provider is the same:

1. Verify the signature over the **raw body**. Nothing is parsed before this.
2. Normalise the provider payload into one shape.
3. Insert the event keyed on ``provider_event_id``. The unique constraint makes a
   replayed webhook a no-op rather than a second event.
4. Acknowledge fast. Processing happens after the response, not before it — a
   provider that times out will retry, and retries must not create duplicates.

The ``duplicate`` flag in the response tells the caller the event was already seen,
so a retrying provider gets a clear signal rather than a silent second delivery.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.messaging import InboundMessageEvent


@dataclass(frozen=True)
class InboundMessage:
    """One normalised inbound message."""

    provider_event_id: str
    channel: str
    channel_user_id: str | None
    content: str | None
    received_at: datetime
    conversation_id: str | None = None
    message_id: str | None = None
    direction: str = "inbound"


class ChannelWebhookAdapter(Protocol):
    """What every inbound channel adapter must provide."""

    channel: str

    def verify(self, *, body: bytes, headers: dict[str, str], secret: str) -> None:
        """Raise ``SignatureError`` unless the request is authentic."""

    def parse(self, *, body: bytes, headers: dict[str, str]) -> list[InboundMessage]:
        """Turn a provider payload into normalised messages."""


class MetaWebhookAdapter:
    """Meta Messenger / Instagram webhook.

    Meta signs the raw body with the app secret and sends ``X-Hub-Signature-256``.
    A challenge handshake (``hub.challenge``) is answered with the echo value and no
    event is produced.
    """

    channel = "messenger"

    def verify(self, *, body: bytes, headers: dict[str, str], secret: str) -> None:
        from xenovarients.platform.webhooks import SignatureError, verify_meta_signature

        signature = headers.get("x-hub-signature-256", "")
        if not signature:
            raise SignatureError("Missing X-Hub-Signature-256 header.")
        verify_meta_signature(body=body, signature=signature, secret=secret)

    def parse(self, *, body: bytes, headers: dict[str, str]) -> list[InboundMessage]:
        payload = json.loads(body)
        if "hub" not in payload:
            # A challenge handshake or an echo — nothing to ingest.
            return []

        messages: list[InboundMessage] = []
        for entry in payload.get("hub", {}).get("entry", []):
            for messaging in entry.get("messaging", []):
                message = messaging.get("message")
                if not message:
                    continue
                sender = messaging.get("sender", {}).get("id")
                received = messaging.get("timestamp")
                received_at = (
                    datetime.fromtimestamp(int(received) / 1000, tz=UTC)
                    if received
                    else datetime.now(UTC)
                )
                messages.append(
                    InboundMessage(
                        provider_event_id=str(messaging.get("mid") or message.get("mid") or ""),
                        channel=self.channel,
                        channel_user_id=str(sender) if sender else None,
                        content=_extract_text(message),
                        received_at=received_at,
                        message_id=str(message.get("mid")) if message.get("mid") else None,
                    )
                )
        return [m for m in messages if m.provider_event_id]


class GenericJsonAdapter:
    """A simple JSON webhook: ``{event_id, channel_user_id, content, received_at}``.

    This is the adapter a stub or self-hosted gateway uses. It carries the same
    timestamp-bound HMAC scheme as the reference provider, so the security properties
    are identical.
    """

    channel = "generic"

    def verify(self, *, body: bytes, headers: dict[str, str], secret: str) -> None:
        from xenovarients.platform.webhooks import SignatureError, verify_hmac_sha256

        signature = headers.get("x-signature", "")
        timestamp = headers.get("x-timestamp")
        if not timestamp:
            raise SignatureError("Missing X-Timestamp header.")
        verify_hmac_sha256(
            body=body,
            signature=signature,
            secret=secret,
            timestamp=int(timestamp),
        )

    def parse(self, *, body: bytes, headers: dict[str, str]) -> list[InboundMessage]:
        payload = json.loads(body)
        received = payload.get("received_at")
        return [
            InboundMessage(
                provider_event_id=str(payload["event_id"]),
                channel=self.channel,
                channel_user_id=payload.get("channel_user_id"),
                content=payload.get("content"),
                received_at=(datetime.fromisoformat(received) if received else datetime.now(UTC)),
                conversation_id=payload.get("conversation_id"),
                message_id=payload.get("message_id"),
            )
        ]


def _extract_text(message: dict[str, Any]) -> str | None:
    text = message.get("text")
    if isinstance(text, str):
        return text
    quick_reply = message.get("quick_reply", {}).get("payload")
    if isinstance(quick_reply, str):
        return quick_reply
    return None


async def ingest(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    adapter: ChannelWebhookAdapter,
    body: bytes,
    headers: dict[str, str],
    secret: str,
) -> tuple[int, bool]:
    """Verify, parse and store an inbound webhook.

    Returns ``(stored, duplicate)``. A replayed webhook stores nothing and reports
    ``duplicate=True``.
    """
    adapter.verify(body=body, headers=headers, secret=secret)
    messages = adapter.parse(body=body, headers=headers)

    stored = 0
    duplicate = False
    for message in messages:
        event = InboundMessageEvent(
            business_id=business_id,
            provider_event_id=message.provider_event_id,
            channel=message.channel,
            channel_user_id=message.channel_user_id,
            conversation_id=message.conversation_id,
            direction=message.direction,
            message_id=message.message_id,
            content=message.content,
            received_at=message.received_at,
        )
        # A nested transaction (savepoint): only this insert is rolled back when the
        # provider_event_id already exists. Rolling back the outer session would
        # discard every other event in this batch.
        try:
            async with session.begin_nested():
                session.add(event)
                await session.flush()
        except IntegrityError:
            duplicate = True
            continue
        stored += 1

    if stored:
        await session.commit()
    return stored, duplicate
