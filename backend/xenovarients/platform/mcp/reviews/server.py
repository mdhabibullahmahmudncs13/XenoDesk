"""Read-only Creator Commerce review tools: the library, consent and card previews.

A review card is only ever *rendered* here. The row — and the consent record behind it —
are created by the admin endpoints, because publishing a customer's words is a
human decision, not a tool call.
"""

from datetime import datetime
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy import func, select

from xenovarients.models.review import ReviewPermission, ReviewReply, ReviewRequest
from xenovarients.platform import reviews
from xenovarients.platform.mcp import external
from xenovarients.platform.mcp.shared import (
    authenticate,
    build_server,
    iso,
    not_found,
    parse_uuid,
    read_only,
    result,
    tenant_session,
)

server = build_server(
    name="reviews",
    title="XenoDesk Reviews",
    instructions=(
        "Read-only answers about captured reviews: browse the review library, check the "
        "consent state of a review request, and preview the card a reply would produce. "
        "No card or consent record is ever created here."
    ),
)


@read_only(server)
async def list_reviews(
    ctx: Context,
    customer_id: str | None = None,
    product_id: str | None = None,
    consent_state: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Browse captured reviews, newest first, filtered by customer, product, consent or date.

    Returns the verbatim reply text and its consent state. A review whose consent was
    revoked is still listed — it is flagged, not hidden.
    """
    principal = await authenticate(ctx)
    async with tenant_session(principal.business_id) as session:
        rows, has_more = await reviews.review_library(
            session,
            business_id=principal.business_id,
            product_id=parse_uuid(product_id, kind="product_id") if product_id else None,
            customer_id=parse_uuid(customer_id, kind="customer_id") if customer_id else None,
            consent_state=consent_state,
            since=since,
            until=until,
            limit=min(max(limit, 1), 100),
        )

    return result(
        reviews=[
            {
                "review_request_id": str(row.review_request_id),
                "reply_id": str(row.reply_id),
                "customer_id": str(row.customer_id),
                "order_id": str(row.order_id) if row.order_id else None,
                "content": row.content,
                "channel": row.channel,
                "received_at": iso(row.received_at),
                "consent_state": row.consent_state,
            }
            for row in rows
        ],
        has_more=has_more,
    )


@read_only(server)
async def review_consent(
    ctx: Context,
    review_request_id: str,
) -> dict[str, Any]:
    """The consent record for one review request, or ``found: false`` if none exists.

    ``pending`` means no answer yet; ``approved`` and ``anonymous`` both allow a card,
    the second without a name. ``declined`` and ``revoked`` do not.
    """
    principal = await authenticate(ctx)
    identifier = parse_uuid(review_request_id, kind="review_request_id")

    async with tenant_session(principal.business_id) as session:
        request = await session.scalar(
            select(ReviewRequest).where(
                ReviewRequest.business_id == principal.business_id,
                ReviewRequest.id == identifier,
            )
        )
        if request is None:
            return not_found("review request", identifier)

        permission = await session.scalar(
            select(ReviewPermission).where(
                ReviewPermission.business_id == principal.business_id,
                ReviewPermission.review_request_id == identifier,
            )
        )
        if permission is None:
            return result(
                review_request_id=str(identifier),
                found=False,
                consent_state=None,
                cards_allowed=False,
                reason="No consent record has been created for this request yet.",
            )
        payload = {
            "review_request_id": str(identifier),
            "found": True,
            "consent_state": permission.state,
            "consent_method": permission.consent_method,
            "review_reply_id": (
                str(permission.review_reply_id) if permission.review_reply_id else None
            ),
            "answered_at": iso(permission.answered_at),
            "revoked_at": iso(permission.revoked_at),
            "consent_text_version": permission.consent_text_version,
        }

    return result(
        **payload,
        cards_allowed=payload["consent_state"] in {"approved", "anonymous"},
    )


@read_only(server)
async def preview_card(
    ctx: Context,
    review_request_id: str,
    template_version: str = "v1",
) -> dict[str, Any]:
    """What the review card for this request would look like — without saving it.

    The display text is the verbatim reply and the label is fixed, exactly as the stored
    card would be. ``persisted`` is always false; creating the card stays an admin action.
    """
    principal = await authenticate(ctx)
    identifier = parse_uuid(review_request_id, kind="review_request_id")

    async with tenant_session(principal.business_id) as session:
        request = await session.scalar(
            select(ReviewRequest).where(
                ReviewRequest.business_id == principal.business_id,
                ReviewRequest.id == identifier,
            )
        )
        if request is None:
            return not_found("review request", identifier)

        preview = await reviews.preview_review_card(
            session,
            business_id=principal.business_id,
            request=request,
            template_version=template_version,
        )

    return result(**preview)


@read_only(server)
async def get_social_sentiment(
    ctx: Context,
    keyword: str,
    limit: int = 25,
) -> dict[str, Any]:
    """Public sentiment for a keyword or brand, beside the reviews this business captured.

    ``external`` is the third-party listening source's answer, or ``available: false``
    with the reason when none is configured. ``captured`` counts this business's own
    replies mentioning the keyword and how many of those may be quoted
    (``approved``/``anonymous`` consent), so public noise is never confused with a
    customer's own words.
    """
    principal = await authenticate(ctx)
    needle = keyword.strip()
    if not needle:
        return result(
            available=False,
            field="social_sentiment",
            reason="no_keyword",
            detail="Pass a brand or product keyword.",
        )

    async with tenant_session(principal.business_id) as session:
        matching = (
            await session.scalar(
                select(func.count(ReviewReply.id)).where(
                    ReviewReply.business_id == principal.business_id,
                    ReviewReply.content.ilike(f"%{needle}%"),
                )
            )
            or 0
        )
        quotable = (
            await session.scalar(
                select(func.count(ReviewReply.id))
                .join(
                    ReviewPermission,
                    ReviewPermission.review_request_id == ReviewReply.review_request_id,
                )
                .where(
                    ReviewReply.business_id == principal.business_id,
                    ReviewPermission.business_id == principal.business_id,
                    ReviewReply.content.ilike(f"%{needle}%"),
                    ReviewPermission.state.in_(("approved", "anonymous")),
                )
            )
            or 0
        )

    return result(
        keyword=needle,
        external=await external.call(
            "social_listening", "get_sentiment", {"keyword": needle, "limit": limit}
        ),
        captured={"matching_reviews": int(matching), "quotable_reviews": int(quotable)},
        note=(
            "Captured reviews are this business's own replies. Only approved or anonymous "
            "ones may be published; the external panel is public context, not consent."
        ),
    )
