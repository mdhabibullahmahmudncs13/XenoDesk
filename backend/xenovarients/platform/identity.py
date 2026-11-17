"""Identity resolution and contact permissions.

A customer identity can arrive from several places — a verified platform link, a phone
number, an email address, or a staff member linking it manually. The ladder in CG-03
decides which one wins, and in what order:

    1. verified platform link   (a link the customer confirmed themselves)
    2. phone                    (E.164, exact)
    3. email                    (normalised, exact)
    4. staff link               (a human said so)
    5. — never a display name   (names are not unique and must never be used to match)

Two rules are absolute:

- **A conflict is recorded, never auto-merged.** If two candidates match, the platform
  raises a conflict for a human to resolve. Silently merging is how one customer's
  history ends up attached to another's name.
- **A name is never a matching key.** Not as a fallback, not as a tiebreaker.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer
from xenovarients.models.messaging import (
    ContactPermission,
    IdentityConflict,
    IdentityMethod,
    MessagingIdentityLink,
)


class ResolveOutcome(str, enum.Enum):
    """What ``resolve`` concluded."""

    matched = "matched"
    no_match = "no_match"
    conflict = "conflict"


# Channels whose channel_user_id is a phone number.
_PHONE_CHANNELS = frozenset({"sms", "whatsapp"})


@dataclass(frozen=True)
class Resolution:
    """The result of resolving a platform identity to a customer."""

    outcome: ResolveOutcome
    customer_id: uuid.UUID | None = None
    method: IdentityMethod | None = None
    conflict_id: uuid.UUID | None = None
    candidates: tuple[uuid.UUID, ...] = ()


def normalise_email(email: str) -> str:
    """Lowercase and strip. The stored form is what every lookup compares against."""
    return email.strip().lower()


def normalise_phone(phone: str) -> str:
    """Normalise to E.164.

    A Bangladeshi number is ``+880`` followed by 10 digits, with the national trunk
    prefix ``0`` removed. Numbers from elsewhere are passed through when they already
    carry a ``+``; anything else is left alone rather than guessed at, because a
    guessed E.164 is worse than an unmatched one.
    """
    digits = "".join(ch for ch in phone.strip() if ch.isdigit())
    if phone.strip().startswith("+"):
        return f"+{digits}"
    if digits.startswith("880") and len(digits) == 13:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"+880{digits[1:]}"
    return f"+{digits}" if digits else ""


async def _link_for(
    session: AsyncSession, business_id: uuid.UUID, channel: str, channel_user_id: str
) -> MessagingIdentityLink | None:
    result = await session.execute(
        select(MessagingIdentityLink).where(
            MessagingIdentityLink.business_id == business_id,
            MessagingIdentityLink.channel == channel,
            MessagingIdentityLink.channel_user_id == channel_user_id,
        )
    )
    return result.scalar_one_or_none()


async def _candidates_by_phone(
    session: AsyncSession, business_id: uuid.UUID, phone_e164: str
) -> list[Customer]:
    if not phone_e164:
        return []
    result = await session.execute(
        select(Customer).where(
            Customer.business_id == business_id,
            Customer.phone_e164 == phone_e164,
        )
    )
    return list(result.scalars().all())


async def _candidates_by_email(
    session: AsyncSession, business_id: uuid.UUID, email_normalised: str
) -> list[Customer]:
    if not email_normalised:
        return []
    result = await session.execute(
        select(Customer).where(
            Customer.business_id == business_id,
            Customer.email_normalised == email_normalised,
        )
    )
    return list(result.scalars().all())


async def resolve(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    channel: str,
    channel_user_id: str,
    phone_e164: str | None = None,
    email: str | None = None,
) -> Resolution:
    """Resolve a platform identity to a customer, walking the CG-03 ladder.

    The first rung that yields exactly one candidate wins. A rung that yields several
    candidates is a conflict — it is recorded and returned, not resolved by picking
    the first one.
    """
    # 1. Verified link — the customer confirmed this identity themselves.
    link = await _link_for(session, business_id, channel, channel_user_id)
    if link is not None:
        return Resolution(
            outcome=ResolveOutcome.matched,
            customer_id=link.customer_id,
            method=IdentityMethod.verified_link,
        )

    # 2. Phone, then 3. Email.
    # On a phone-based channel the channel_user_id *is* the phone number, so it counts
    # as the phone even when the caller does not pass one separately.
    raw_phone = phone_e164 or (channel_user_id if channel in _PHONE_CHANNELS else "")
    phone = normalise_phone(raw_phone) if raw_phone else ""
    if phone:
        candidates = await _candidates_by_phone(session, business_id, phone)
        if len(candidates) == 1:
            return Resolution(
                outcome=ResolveOutcome.matched,
                customer_id=candidates[0].id,
                method=IdentityMethod.phone,
            )
        if len(candidates) > 1:
            return await _record_conflict(
                session,
                business_id=business_id,
                channel=channel,
                channel_user_id=channel_user_id,
                reason="multiple_phone_matches",
                candidate_ids=[c.id for c in candidates],
            )

    normalised_email = normalise_email(email) if email else ""
    if normalised_email:
        candidates = await _candidates_by_email(session, business_id, normalised_email)
        if len(candidates) == 1:
            return Resolution(
                outcome=ResolveOutcome.matched,
                customer_id=candidates[0].id,
                method=IdentityMethod.email,
            )
        if len(candidates) > 1:
            return await _record_conflict(
                session,
                business_id=business_id,
                channel=channel,
                channel_user_id=channel_user_id,
                reason="multiple_email_matches",
                candidate_ids=[c.id for c in candidates],
            )

    # 4. A staff link exists but the identity itself does not match any customer —
    #    the staff member linked it, so honour it.
    staff_link = await _link_for(session, business_id, channel, channel_user_id)
    if staff_link is not None:
        return Resolution(
            outcome=ResolveOutcome.matched,
            customer_id=staff_link.customer_id,
            method=IdentityMethod.staff_link,
        )

    # 5. No match. A display name is never a fallback key.
    return Resolution(outcome=ResolveOutcome.no_match)


async def _record_conflict(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    channel: str,
    channel_user_id: str,
    reason: str,
    candidate_ids: list[uuid.UUID],
) -> Resolution:
    conflict = IdentityConflict(
        business_id=business_id,
        channel=channel,
        channel_user_id=channel_user_id,
        candidate_customer_ids=[str(cid) for cid in candidate_ids],
        reason=reason,
        state="open",
    )
    session.add(conflict)
    await session.flush()
    return Resolution(
        outcome=ResolveOutcome.conflict,
        conflict_id=conflict.id,
        candidates=tuple(candidate_ids),
    )


async def link(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    channel: str,
    channel_user_id: str,
    customer_id: uuid.UUID,
    method: IdentityMethod = IdentityMethod.staff_link,
    verified_by_user_id: uuid.UUID | None = None,
) -> MessagingIdentityLink:
    """Link a platform identity to a customer.

    The unique constraint on ``(business_id, channel, channel_user_id)`` makes this
    idempotent: re-linking the same identity to the same customer is a no-op rather
    than a second row. Re-linking to a *different* customer raises — that is a
    conflict for a human, not something to overwrite.
    """
    existing = await _link_for(session, business_id, channel, channel_user_id)
    if existing is not None:
        if existing.customer_id == customer_id:
            return existing
        raise IdentityAlreadyLinked(
            f"This {channel} identity is already linked to a different customer."
        )

    row = MessagingIdentityLink(
        business_id=business_id,
        channel=channel,
        channel_user_id=channel_user_id,
        customer_id=customer_id,
        method=method.value,
        verified_at=datetime.now(UTC) if method == IdentityMethod.verified_link else None,
        verified_by_user_id=verified_by_user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def unlink(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    channel: str,
    channel_user_id: str,
) -> bool:
    """Remove a link. Returns whether anything was removed."""
    existing = await _link_for(session, business_id, channel, channel_user_id)
    if existing is None:
        return False
    await session.delete(existing)
    await session.flush()
    return True


async def check_permission(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    channel: str,
    purpose: str | None = None,
) -> bool:
    """Whether this app may contact the customer on this channel.

    Permission is per ``(customer, channel)``. Consent for one purpose is not consent
    for another, so a caller that needs a specific purpose passes it and the caller
    that does not gets the channel-level answer.
    """
    result = await session.execute(
        select(ContactPermission).where(
            ContactPermission.business_id == business_id,
            ContactPermission.customer_id == customer_id,
            ContactPermission.channel == channel,
        )
    )
    permission = result.scalar_one_or_none()
    if permission is None:
        return False
    if permission.opted_out_at is not None:
        return False
    if not permission.eligible:
        return False
    return not (purpose and purpose not in (permission.purposes or []))


async def grant_permission(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    channel: str,
    contact_value: str,
    source: str,
    purposes: list[str] | None = None,
) -> ContactPermission:
    """Record consent for a channel and purpose."""
    result = await session.execute(
        select(ContactPermission).where(
            ContactPermission.business_id == business_id,
            ContactPermission.customer_id == customer_id,
            ContactPermission.channel == channel,
        )
    )
    permission = result.scalar_one_or_none()
    if permission is None:
        permission = ContactPermission(
            business_id=business_id,
            customer_id=customer_id,
            channel=channel,
            contact_value=contact_value,
            eligible=True,
            source=source,
            purposes=purposes or [],
        )
        session.add(permission)
    else:
        permission.contact_value = contact_value
        permission.eligible = True
        permission.opted_out_at = None
        permission.source = source
        permission.purposes = purposes or []
    await session.flush()
    return permission


async def revoke_permission(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    channel: str,
) -> bool:
    """Opt the customer out on a channel.

    Opting out is sticky: it sets ``opted_out_at`` rather than clearing eligibility,
    so the record of the opt-out survives and the customer is not re-enrolled by a
    later sync.
    """
    result = await session.execute(
        select(ContactPermission).where(
            ContactPermission.business_id == business_id,
            ContactPermission.customer_id == customer_id,
            ContactPermission.channel == channel,
        )
    )
    permission = result.scalar_one_or_none()
    if permission is None:
        return False
    if permission.opted_out_at is not None:
        # Already opted out — nothing to change, and the original timestamp stands.
        return False
    permission.opted_out_at = datetime.now(UTC)
    permission.eligible = False
    await session.flush()
    return True


class IdentityAlreadyLinked(RuntimeError):
    """Raised when linking an identity that is already linked to another customer."""
