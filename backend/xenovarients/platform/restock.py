"""Restore Product: waiting lists, detection, preview, confirm, history (RP-02…RP-10).

**Detection never sends.** The polling worker writes ``restock_events`` and an owner
notification, and nothing else. The only path to ``outbound_messages`` is
``confirm_batch``, which a human triggers. That is the product's first rule: nothing
reaches a customer without a human decision.

**The waiting list is grouped by product *and* variant** (RP-03). Two variants of the
same product are two lists with two counts; they are never mixed.

**Eligibility at preview is a prediction, not a promise** (RP-06, RP-08). The preview
evaluates the channel rules and reports them per recipient; the dispatcher re-checks
at send time, because consent can be withdrawn in between.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer, Product, ProductVariant
from xenovarients.models.messaging import ContactPermission, MessagingIdentityLink
from xenovarients.models.outbound import (
    MessageTemplate,
    OutboundMessage,
    OutboundPurpose,
    SkipReason,
)
from xenovarients.models.platform import NotificationKind
from xenovarients.models.restock import (
    BatchState,
    ProductInterest,
    RestockBatch,
    RestockEvent,
)
from xenovarients.models.tenancy import Business
from xenovarients.platform import audit
from xenovarients.platform.eligibility import EligibilityDecision, load_rules
from xenovarients.platform.eligibility import check as check_eligibility
from xenovarients.platform.notifications import notify
from xenovarients.platform.outbound import enqueue, mark_skipped
from xenovarients.platform.source import CustomerOrderSource

# Channel preference for a restock (RP-06): the two that reach anyone, then the two
# that only work while a provider window is open.
CHANNEL_ORDER = ("email", "sms", "messenger", "whatsapp")

# The merge fields a template may use (RP-05).
MERGE_FIELDS = ("customer_name", "request_date", "product_name", "business_name")

# RP-09: a restock message must never imply the stock is held for the reader. Template
# save-time validation has no save path yet (no template CRUD), so it runs at preview.
RESERVATION_PHRASES = ("reserved", "reservation", "set aside", "held for you", "guaranteed")

MAX_GROUPS = 100


class ReservationLanguageRejected(ValueError):
    """A template promises to reserve stock, which the platform cannot honour."""


@dataclass(frozen=True)
class WaitingEntry:
    """One customer waiting for one variant (RP-02)."""

    interest_id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str | None
    contact_channel: str
    contact_value: str
    requested_at: datetime
    quantity: int | None


@dataclass(frozen=True)
class WaitingGroup:
    """One variant's waiting list (RP-03)."""

    product_id: uuid.UUID
    product_name: str
    variant_id: uuid.UUID
    variant_name: str
    stock_on_hand: int
    is_available: bool
    waiting_count: int
    entries: tuple[WaitingEntry, ...]


@dataclass(frozen=True)
class PreviewRecipient:
    """One recipient as the owner sees them before confirming (RP-07)."""

    interest_id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str | None
    channel: str
    contact_value: str
    body: str
    eligible: bool
    skip_reason: str | None


@dataclass(frozen=True)
class BatchPreview:
    """What would happen if the owner confirmed now."""

    recipients: tuple[PreviewRecipient, ...]
    waiting_count: int
    stock_after: int
    stock_warning: dict[str, Any] | None

    @property
    def eligible_count(self) -> int:
        return sum(1 for recipient in self.recipients if recipient.eligible)

    @property
    def skipped_count(self) -> int:
        return len(self.recipients) - self.eligible_count


@dataclass(frozen=True)
class Confirmation:
    """The batch a confirmation created."""

    batch: RestockBatch
    queued: int
    duplicates: int
    skipped: tuple[tuple[uuid.UUID, str], ...]
    stock_warning: dict[str, Any] | None


@dataclass(frozen=True)
class DetectionReport:
    """What one detection poll did."""

    transitions: int = 0
    events_created: int = 0
    notifications_created: int = 0


async def waiting_list(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    product_id: uuid.UUID | None = None,
    variant_id: uuid.UUID | None = None,
    limit: int = 25,
) -> tuple[list[WaitingGroup], bool]:
    """The waiting lists, grouped by product and variant, newest request first.

    The page is taken over groups, not over customers: groups are (product, variant)
    pairs, a bounded set. ``has_more`` says whether another page exists.
    """
    capped = min(max(limit, 1), MAX_GROUPS)

    conditions = [ProductInterest.business_id == business_id]
    if product_id is not None:
        conditions.append(ProductInterest.product_id == product_id)
    if variant_id is not None:
        conditions.append(ProductInterest.variant_id == variant_id)

    groups_result = await session.execute(
        select(
            ProductInterest.product_id,
            ProductInterest.variant_id,
            func.max(ProductInterest.requested_at).label("latest"),
            func.count(ProductInterest.id).label("waiting_count"),
        )
        .where(*conditions)
        .group_by(ProductInterest.product_id, ProductInterest.variant_id)
        .order_by(func.max(ProductInterest.requested_at).desc(), ProductInterest.variant_id)
        .limit(capped + 1)
    )
    group_rows = list(groups_result.all())
    has_more = len(group_rows) > capped
    page_rows = group_rows[:capped]
    if not page_rows:
        return [], False

    pairs = [(row.product_id, row.variant_id) for row in page_rows]
    entries_result = await session.execute(
        select(
            ProductInterest,
            Customer.name,
            Product.name,
            ProductVariant.name,
            ProductVariant.stock_on_hand,
            ProductVariant.is_available,
        )
        .join(Customer, Customer.id == ProductInterest.customer_id)
        .join(Product, Product.id == ProductInterest.product_id)
        .join(ProductVariant, ProductVariant.id == ProductInterest.variant_id)
        .where(
            ProductInterest.business_id == business_id,
            tuple_(ProductInterest.product_id, ProductInterest.variant_id).in_(pairs),
        )
        .order_by(ProductInterest.requested_at)
    )

    by_group: dict[tuple[uuid.UUID, uuid.UUID], list[WaitingEntry]] = {}
    details: dict[tuple[uuid.UUID, uuid.UUID], tuple[str, str, int, bool]] = {}
    for row in entries_result.all():
        interest: ProductInterest = row[0]
        key = (interest.product_id, interest.variant_id)
        details[key] = (row[2], row[3], row[4], row[5])
        by_group.setdefault(key, []).append(
            WaitingEntry(
                interest_id=interest.id,
                customer_id=interest.customer_id,
                customer_name=row[1],
                contact_channel=interest.contact_channel,
                contact_value=interest.contact_value,
                requested_at=interest.requested_at,
                quantity=interest.quantity,
            )
        )

    groups = [
        WaitingGroup(
            product_id=row.product_id,
            product_name=details[(row.product_id, row.variant_id)][0],
            variant_id=row.variant_id,
            variant_name=details[(row.product_id, row.variant_id)][1],
            stock_on_hand=details[(row.product_id, row.variant_id)][2],
            is_available=details[(row.product_id, row.variant_id)][3],
            waiting_count=row.waiting_count,
            entries=tuple(by_group.get((row.product_id, row.variant_id), [])),
        )
        for row in page_rows
    ]
    return groups, has_more


async def add_interest(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    product_id: uuid.UUID,
    variant_id: uuid.UUID,
    contact_channel: str,
    contact_value: str,
    requested_at: datetime | None = None,
    quantity: int | None = None,
    created_by_user_id: uuid.UUID | None = None,
    source: str = "staff",
) -> ProductInterest:
    """Record one "Add to waiting list" (RP-02). The caller validates the ids."""
    row = ProductInterest(
        business_id=business_id,
        customer_id=customer_id,
        product_id=product_id,
        variant_id=variant_id,
        requested_at=requested_at or datetime.now(UTC),
        quantity=quantity,
        contact_channel=contact_channel,
        contact_value=contact_value,
        source=source,
        created_by_user_id=created_by_user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def detect_restocks(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    source: CustomerOrderSource,
    fetched_at: datetime | None = None,
) -> DetectionReport:
    """Find variants that moved from unavailable to available (RP-04).

    Compares the source against the mirror *before* it is refreshed, so the transition
    is the one the platform last saw. Writes a ``restock_events`` row and an owner
    notification; writes no message, and has no route to one.

    Run it before ``sync_inventory``, never after — the sync overwrites the state this
    comparison depends on.
    """
    moment = fetched_at or datetime.now(UTC)
    stored_result = await session.execute(
        select(ProductVariant).where(ProductVariant.business_id == business_id)
    )
    stored = {
        variant.source_variant_id: variant
        for variant in stored_result.scalars().all()
        if variant.source_variant_id is not None
    }

    transitions = events = notifications = 0
    async for record in _inventory_pages(source):
        for source_variant in getattr(record, "variants", ()):
            previous = stored.get(source_variant.source_variant_id)
            if previous is None or previous.is_available or not source_variant.is_available:
                continue
            transitions += 1

            event = RestockEvent(
                business_id=business_id,
                product_id=previous.product_id,
                variant_id=previous.id,
                detected_at=moment,
                stock_after=source_variant.stock_on_hand,
                source="poll",
                # One row per transition, not per poll: the timestamp is part of the
                # key, so a re-run of the same poll hits the constraint and stays quiet.
                source_ref=f"{source_variant.source_variant_id}@{moment.isoformat()}",
            )
            try:
                async with session.begin_nested():
                    session.add(event)
                    await session.flush()
            except IntegrityError:
                continue
            events += 1

            await notify(
                session,
                business_id=business_id,
                kind=NotificationKind.restock,
                title=f"{source_variant.product_name} — {source_variant.variant_name} is back",
                body=f"{source_variant.stock_on_hand} in stock.",
                payload={
                    "restock_event_id": str(event.id),
                    "product_id": str(previous.product_id),
                    "variant_id": str(previous.id),
                    "stock_after": source_variant.stock_on_hand,
                },
            )
            event.notified_owner_at = moment
            await session.flush()
            notifications += 1

    return DetectionReport(
        transitions=transitions,
        events_created=events,
        notifications_created=notifications,
    )


async def preview(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    event: RestockEvent,
    template: MessageTemplate,
    channel_overrides: dict[str, str] | None = None,
    rules: dict[str, Any] | None = None,
) -> BatchPreview:
    """What confirming this event would send (RP-05…RP-07, RP-09). Nothing is written."""
    validate_template(template.body)
    active_rules = rules or load_rules()

    entries = await _entries_for_variant(
        session,
        business_id=business_id,
        product_id=event.product_id,
        variant_id=event.variant_id,
    )
    business = await session.scalar(select(Business).where(Business.id == business_id))
    product_name = (
        await session.scalar(select(Product.name).where(Product.id == event.product_id))
    ) or ""
    permissions = await _permissions(session, business_id=business_id)
    links = await _identity_links(session, business_id=business_id)

    recipients: list[PreviewRecipient] = []
    for entry in entries:
        channel, value, decision = _choose_channel(
            active_rules,
            entry=entry,
            permissions=permissions,
            links=links,
            overrides=channel_overrides or {},
        )
        recipients.append(
            PreviewRecipient(
                interest_id=entry.interest_id,
                customer_id=entry.customer_id,
                customer_name=entry.customer_name,
                channel=channel,
                contact_value=value or "",
                body=render(
                    template.body,
                    {
                        "customer_name": entry.customer_name or "",
                        "request_date": entry.requested_at.date().isoformat(),
                        "product_name": product_name,
                        "business_name": business.name if business is not None else "",
                    },
                ),
                eligible=decision.eligible,
                skip_reason=decision.reason,
            )
        )

    eligible = sum(1 for recipient in recipients if recipient.eligible)
    warning = None
    if event.stock_after < eligible:
        # RP-09: the numbers, and no promise that any of it is reserved.
        warning = {
            "stock_after": event.stock_after,
            "waiting_demand": eligible,
            "message": (
                f"{event.stock_after} available for {eligible} customers waiting. "
                "Stock is not reserved."
            ),
        }

    return BatchPreview(
        recipients=tuple(recipients),
        waiting_count=len(recipients),
        stock_after=event.stock_after,
        stock_warning=warning,
    )


async def confirm_batch(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    event: RestockEvent,
    template: MessageTemplate,
    batch_preview: BatchPreview,
    approved_by_user_id: uuid.UUID,
    idempotency_key: str,
) -> Confirmation:
    """Queue the batch an owner confirmed (RP-07, RP-08).

    An ineligible recipient gets a ``skipped`` message row with the reason, so the
    reason survives in the delivery log. A recipient already queued by an earlier
    confirmation of this event is a duplicate and is not queued twice.
    """
    batch = RestockBatch(
        business_id=business_id,
        restock_event_id=event.id,
        approved_by_user_id=approved_by_user_id,
        approved_at=datetime.now(UTC),
        template_id=template.id,
        template_version=str(template.version),
        state=BatchState.queued.value,
        idempotency_key=idempotency_key,
    )
    session.add(batch)
    await session.flush()

    queued = 0
    duplicates = 0
    skipped: list[tuple[uuid.UUID, str]] = []

    for recipient in batch_preview.recipients:
        key = outbound_key(
            business_id=business_id,
            restock_event_id=event.id,
            interest_id=recipient.interest_id,
            channel=recipient.channel,
        )
        existing = await session.scalar(
            select(OutboundMessage.id).where(OutboundMessage.idempotency_key == key)
        )
        if existing is not None:
            duplicates += 1
            skipped.append((recipient.customer_id, "duplicate"))
            continue

        message = await enqueue(
            session,
            business_id=business_id,
            purpose=OutboundPurpose.restock.value,
            ref_id=batch.id,
            customer_id=recipient.customer_id,
            channel=recipient.channel,
            to_address=recipient.contact_value,
            body=recipient.body,
            idempotency_key=key,
        )
        if recipient.eligible:
            queued += 1
        else:
            reason = _skip_reason(recipient.skip_reason)
            await mark_skipped(session, message=message, reason=reason)
            skipped.append((recipient.customer_id, reason.value))

    batch.recipient_count = queued
    batch.skipped_count = len(skipped)
    await audit.record(
        session,
        business_id=business_id,
        action=audit.AuditAction.batch_approved,
        target_type="restock_batch",
        target_id=str(batch.id),
        actor_user_id=approved_by_user_id,
        metadata={
            "restock_event_id": str(event.id),
            "queued": queued,
            "skipped": len(skipped),
            "duplicates": duplicates,
            "stock_warning": batch_preview.stock_warning is not None,
        },
    )
    await session.flush()

    return Confirmation(
        batch=batch,
        queued=queued,
        duplicates=duplicates,
        skipped=tuple(skipped),
        stock_warning=batch_preview.stock_warning,
    )


async def delivery_history(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    event_id: uuid.UUID,
) -> list[OutboundMessage]:
    """Every message queued for an event, with its state and skip reason (RP-10)."""
    batch_ids = list(
        (
            await session.execute(
                select(RestockBatch.id).where(
                    RestockBatch.business_id == business_id,
                    RestockBatch.restock_event_id == event_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not batch_ids:
        return []
    result = await session.execute(
        select(OutboundMessage)
        .where(
            OutboundMessage.business_id == business_id,
            OutboundMessage.purpose == OutboundPurpose.restock.value,
            OutboundMessage.ref_id.in_(batch_ids),
        )
        .order_by(OutboundMessage.created_at)
    )
    return list(result.scalars().all())


def render(body: str, fields: dict[str, str]) -> str:
    """Fill the merge fields. An unknown placeholder is left as it is, visibly."""
    for key in MERGE_FIELDS:
        body = body.replace("{{" + key + "}}", fields.get(key, ""))
    return body


def validate_template(body: str) -> None:
    """Reject a template that promises to reserve stock (RP-09)."""
    lowered = body.lower()
    for phrase in RESERVATION_PHRASES:
        if phrase in lowered:
            raise ReservationLanguageRejected(
                f"A restock message must not promise stock: it contains '{phrase}'."
            )


def outbound_key(
    *,
    business_id: uuid.UUID,
    restock_event_id: uuid.UUID,
    interest_id: uuid.UUID,
    channel: str,
) -> str:
    """The RP-08 idempotency key: business + event + interest + channel."""
    raw = f"{business_id}|{restock_event_id}|{interest_id}|{channel}"
    return hashlib.sha256(raw.encode()).hexdigest()


def batch_key(*, business_id: uuid.UUID, request_key: str) -> str:
    """The batch's key: the client's header, scoped to the tenant and hashed to fit."""
    return hashlib.sha256(f"{business_id}|{request_key}".encode()).hexdigest()


def _skip_reason(reason: str | None) -> SkipReason:
    """Map an eligibility code onto the delivery log's skip reasons."""
    if reason == "opted_out":
        return SkipReason.opted_out
    if reason in {"no_consent", "no_verified_identity"}:
        return SkipReason.no_permission
    if reason == "no_valid_contact_value":
        return SkipReason.invalid_address
    return SkipReason.channel_ineligible


def _choose_channel(
    rules: dict[str, Any],
    *,
    entry: WaitingEntry,
    permissions: dict[tuple[uuid.UUID, str], ContactPermission],
    links: dict[tuple[uuid.UUID, str], str],
    overrides: dict[str, str],
) -> tuple[str, str | None, EligibilityDecision]:
    """The first channel this customer can actually be reached on.

    When none is eligible, returns the first channel's decision, so the preview says
    *why* rather than leaving the reason blank.
    """
    override = overrides.get(str(entry.customer_id))
    candidates = (override,) if override in CHANNEL_ORDER else CHANNEL_ORDER

    first: tuple[str, str | None, EligibilityDecision] | None = None
    for channel in candidates:
        permission = permissions.get((entry.customer_id, channel))
        value = _contact_value(entry, permission, links.get((entry.customer_id, channel)), channel)
        decision = check_eligibility(
            rules,
            channel=channel,
            has_consent=_has_consent(permission),
            has_verified_identity=(entry.customer_id, channel) in links,
            opted_out=permission is not None and permission.opted_out_at is not None,
            has_contact_value=bool(value),
            channel_enabled=bool(rules.get("defaults", {}).get(channel, False)),
            # No approved business-initiated template is stored yet, so a channel that
            # needs one stays ineligible until template approval exists.
            has_approved_template=False,
        )
        if decision.eligible:
            return channel, value, decision
        if first is None:
            first = (channel, value, decision)

    if first is not None:
        return first
    return "email", None, EligibilityDecision(eligible=False, reason="channel_not_enabled")


def _has_consent(permission: ContactPermission | None) -> bool:
    """A permission row counts only when it covers the restock purpose."""
    if permission is None:
        return False
    purposes = permission.purposes or []
    return not purposes or OutboundPurpose.restock.value in purposes


def _contact_value(
    entry: WaitingEntry,
    permission: ContactPermission | None,
    link_value: str | None,
    channel: str,
) -> str | None:
    """The address to send to on this channel, from the most specific source."""
    if link_value:
        return link_value
    if permission is not None and permission.contact_value:
        return permission.contact_value
    if entry.contact_channel == channel and entry.contact_value:
        return entry.contact_value
    return None


async def _entries_for_variant(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    product_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> list[WaitingEntry]:
    """Every waiting customer for one product+variant, oldest request first."""
    result = await session.execute(
        select(ProductInterest, Customer.name)
        .join(Customer, Customer.id == ProductInterest.customer_id)
        .where(
            ProductInterest.business_id == business_id,
            ProductInterest.product_id == product_id,
            ProductInterest.variant_id == variant_id,
        )
        .order_by(ProductInterest.requested_at)
    )
    return [
        WaitingEntry(
            interest_id=interest.id,
            customer_id=interest.customer_id,
            customer_name=name,
            contact_channel=interest.contact_channel,
            contact_value=interest.contact_value,
            requested_at=interest.requested_at,
            quantity=interest.quantity,
        )
        for interest, name in result.all()
    ]


async def _permissions(
    session: AsyncSession, *, business_id: uuid.UUID
) -> dict[tuple[uuid.UUID, str], ContactPermission]:
    """The consent rows for this business, keyed by (customer, channel)."""
    result = await session.execute(
        select(ContactPermission).where(ContactPermission.business_id == business_id)
    )
    return {(row.customer_id, row.channel): row for row in result.scalars().all()}


async def _identity_links(
    session: AsyncSession, *, business_id: uuid.UUID
) -> dict[tuple[uuid.UUID, str], str]:
    """Every platform link, keyed by (customer, channel) → channel_user_id."""
    result = await session.execute(
        select(MessagingIdentityLink).where(MessagingIdentityLink.business_id == business_id)
    )
    return {(row.customer_id, row.channel): row.channel_user_id for row in result.scalars().all()}


async def _inventory_pages(source: CustomerOrderSource) -> AsyncIterator[Any]:
    """Follow the source's inventory cursors to the end."""
    cursor: str | None = None
    while True:
        page = await source.fetch_inventory(cursor)
        for record in page.records:
            yield record
        cursor = page.next_cursor
        if not cursor:
            return
