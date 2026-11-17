"""Generic request idempotency: store a response, replay it on a repeat.

Most idempotency in this system is a database constraint on a domain table — the
``restock_batches.idempotency_key``, the ``outbound_messages.idempotency_key``,
the ``provider_event_id``. Those are the real guarantees, and they hold even if the
API process dies.

This module is the generic HTTP-level belt on top: it records the *response* of a
request that carried an ``Idempotency-Key`` and replays it verbatim when the same
key comes back. Two properties matter:

1. **A different body with the same key is a 409, not a replay.** Replaying would
   silently perform the first request's action for a second request's intent. The
   fingerprint makes that mismatch explicit.
2. **A concurrent repeat does not run the action twice.** The record is inserted
   *before* the handler runs, so the second request sees the record and waits for
   or replays it rather than racing into the handler.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.platform import IdempotencyRecord


@dataclass(frozen=True)
class StoredResponse:
    """A response that was recorded for an idempotency key."""

    status_code: int
    body: dict[str, Any]
    headers: dict[str, Any]


class IdempotencyConflict(Exception):
    """Raised when the same key arrives with a different request body."""


def fingerprint(method: str, path: str, body: bytes) -> str:
    """A hash of the request that a key is bound to.

    The method and path are part of it: the same key sent to a different endpoint
    is a different request, not a retry of this one.
    """
    digest = hashlib.sha256()
    digest.update(method.upper().encode())
    digest.update(b"\n")
    digest.update(path.encode())
    digest.update(b"\n")
    digest.update(body)
    return digest.hexdigest()


async def find(
    session: AsyncSession,
    *,
    business_id: Any,
    key: str,
    endpoint: str,
) -> IdempotencyRecord | None:
    """The record for this key and endpoint, if there is one."""
    record: IdempotencyRecord | None = await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.business_id == business_id,
            IdempotencyRecord.key == key,
            IdempotencyRecord.endpoint == endpoint,
        )
    )
    return record


async def claim(
    session: AsyncSession,
    *,
    business_id: Any,
    key: str,
    endpoint: str,
    request_fingerprint: str,
) -> tuple[IdempotencyRecord, bool]:
    """Claim a key for this request.

    Returns ``(record, is_new)``. ``is_new`` is True when this caller created the
    record and may run the action; False when the record already existed and the
    response should be replayed.

    Raises ``IdempotencyConflict`` if the record exists but the request body
    differs.
    """
    existing = await find(session, business_id=business_id, key=key, endpoint=endpoint)
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyConflict(
                "This Idempotency-Key was already used with a different request body."
            )
        return existing, False

    record = IdempotencyRecord(
        business_id=business_id,
        key=key,
        endpoint=endpoint,
        request_fingerprint=request_fingerprint,
        status_code=0,
        response_body={},
        response_headers={},
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError:
        # Another request claimed the key between our SELECT and our INSERT.
        await session.rollback()
        existing = await find(session, business_id=business_id, key=key, endpoint=endpoint)
        if existing is None:
            raise
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyConflict(
                "This Idempotency-Key was already used with a different request body."
            ) from None
        return existing, False
    return record, True


async def store_response(
    session: AsyncSession,
    *,
    record: IdempotencyRecord,
    status_code: int,
    body: dict[str, Any],
    headers: dict[str, Any] | None = None,
) -> IdempotencyRecord:
    """Record the response so a repeat can replay it."""
    record.status_code = status_code
    record.response_body = body
    record.response_headers = headers or {}
    await session.flush()
    return record


def as_stored(record: IdempotencyRecord) -> StoredResponse:
    """The record as a replayable response."""
    return StoredResponse(
        status_code=record.status_code,
        body=record.response_body or {},
        headers=record.response_headers or {},
    )


def parse_body(raw: bytes) -> dict[str, Any]:
    """The response body as a JSON object.

    A response that is not JSON is stored as an empty object — there is nothing to
    replay, and the status code plus headers still tell the client what happened.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {"data": parsed}
