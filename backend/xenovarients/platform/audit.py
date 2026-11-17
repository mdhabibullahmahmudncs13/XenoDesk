"""Audit log service.

The ``audit_log`` table is append-only — a Postgres trigger rejects UPDATE and DELETE
on it. This module is the only supported way to write to it.

Two properties matter and are easy to get wrong:

1. **Before/after are hashes, never payloads.** A batch of 5,000 recipients cannot be
   stored in a log row, and a log is the wrong place for PII. The hash is enough to
   prove *that* a payload changed, not to reconstruct it.
2. **The write is part of the caller's transaction.** If the audited action fails, the
   audit row must fail with it — an audit trail that records things that did not
   happen is worse than no trail.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.core.security import hash_payload
from xenovarients.models.tenancy import AuditLog


class AuditAction:
    """Stable action names. The frontend groups on these, so do not reword freely."""

    batch_approved = "batch_approved"
    batch_cancelled = "batch.cancelled"
    consent_changed = "consent.changed"
    consent_revoked = "consent.revoked"
    export_created = "export.created"
    identity_linked = "identity.linked"
    identity_unlinked = "identity.unlinked"
    identity_conflict_resolved = "identity.conflict_resolved"
    role_changed = "role.changed"
    settings_changed = "settings.changed"
    faq_created = "faq.created"
    faq_updated = "faq.updated"
    review_sent = "review.sent"


async def record(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: str,
    actor_user_id: uuid.UUID | None = None,
    before: dict[str, Any] | str | None = None,
    after: dict[str, Any] | str | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Append one audit entry.

    ``before`` and ``after`` are hashed rather than stored, so the row stays small and
    carries no PII. Pass a pre-serialised string if the caller already has one.
    """
    entry = AuditLog(
        business_id=business_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        before_hash=_hash(before),
        after_hash=_hash(after),
        metadata_json=metadata or {},
        ip_address=ip_address,
    )
    session.add(entry)
    return entry


def _hash(payload: dict[str, Any] | str | None) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        return hash_payload(payload)
    import json

    return hash_payload(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))
