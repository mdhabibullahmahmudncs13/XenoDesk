"""The Customer Genome endpoints: repeat buyers, customer history, identity links.

Every endpoint reads the tenant from the token, never from the request. The figures
are derived from the authoritative history at read time (CG-09), so a correction in
the source shows up here rather than waiting for the next sync.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_principal, get_tenant_session
from xenovarients.api.errors import NotFound
from xenovarients.api.pagination import Page
from xenovarients.models.customer import Customer
from xenovarients.models.messaging import IdentityMethod
from xenovarients.platform.genome import (
    customer_directory,
    customer_figures,
    customer_history,
    product_catalogue,
    repeat_buyers,
)
from xenovarients.platform.identity import link

router = APIRouter(prefix="/api/v1", tags=["customer-genome"])


class RepeatBuyerOut(BaseModel):
    """One row of the Repeat Buyers list (CG-01)."""

    id: str
    name: str | None = None
    phone_e164: str | None = None
    email_normalised: str | None = None
    order_count: int
    total_spend: str
    currency: str
    last_purchase_at: str | None = None
    history_url: str


class HistoryItemOut(BaseModel):
    """One product line on an order."""

    product_id: str
    variant_id: str | None = None
    product_name: str
    quantity: int
    line_total: str


class HistoryEntryOut(BaseModel):
    """One order in the timeline (CG-02)."""

    id: str
    source_order_id: str
    ordered_at: str
    status: str
    qualifying: bool
    total_amount: str
    refund_amount: str
    currency: str
    items: list[HistoryItemOut] = []


class CustomerHistoryOut(BaseModel):
    """A customer's order timeline."""

    customer_id: str
    name: str | None = None
    order_count: int
    total_spend: str
    currency: str
    last_purchase_at: str | None = None
    data_as_of: str
    items: list[HistoryEntryOut] = []
    next_cursor: str | None = None
    has_more: bool = False


class DirectoryCustomerOut(BaseModel):
    """One customer in the searchable directory."""

    id: str
    name: str | None = None
    phone_e164: str | None = None
    email_normalised: str | None = None
    order_count: int
    total_spend: str
    currency: str
    last_purchase_at: str | None = None
    is_repeat_buyer: bool
    history_url: str


class DirectoryOut(BaseModel):
    items: list[DirectoryCustomerOut]
    has_more: bool = False


@router.get("/customer-genome/customers")
async def search_customers(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=25, ge=1, le=100),
) -> DirectoryOut:
    """Search this business's customers by name, phone or email.

    Every customer is searchable, not only repeat buyers, so staff can open a
    history or add a first-time buyer to a waiting list.
    """
    entries, has_more = await customer_directory(
        session, business_id=principal.business_id, query=q, limit=limit
    )
    return DirectoryOut(
        items=[
            DirectoryCustomerOut(
                id=str(entry.customer_id),
                name=entry.name,
                phone_e164=entry.phone_e164,
                email_normalised=entry.email_normalised,
                order_count=entry.order_count,
                total_spend=str(entry.total_spend),
                currency=entry.currency,
                last_purchase_at=(
                    entry.last_purchase_at.isoformat() if entry.last_purchase_at else None
                ),
                is_repeat_buyer=entry.is_repeat_buyer,
                history_url=f"/customer-genome/history?customer_id={entry.customer_id}",
            )
            for entry in entries
        ],
        has_more=has_more,
    )


class CatalogueVariantOut(BaseModel):
    id: str
    name: str
    is_available: bool
    stock_on_hand: int


class CatalogueProductOut(BaseModel):
    id: str
    name: str
    category: str | None = None
    variants: list[CatalogueVariantOut] = []


class CatalogueOut(BaseModel):
    items: list[CatalogueProductOut] = []


@router.get("/customer-genome/products")
async def list_products(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
) -> CatalogueOut:
    """Products and their variants — the waiting-list form's choices (RP-02)."""
    products = await product_catalogue(
        session, business_id=principal.business_id, query=q, limit=limit
    )
    return CatalogueOut(
        items=[
            CatalogueProductOut(
                id=str(product.product_id),
                name=product.name,
                category=product.category,
                variants=[
                    CatalogueVariantOut(
                        id=str(variant.variant_id),
                        name=variant.name,
                        is_available=variant.is_available,
                        stock_on_hand=variant.stock_on_hand,
                    )
                    for variant in product.variants
                ],
            )
            for product in products
        ]
    )


class LinkIdentityRequest(BaseModel):
    """The staff "Link customer" action (CG-03, CG-10)."""

    channel: str
    channel_user_id: str
    method: str = IdentityMethod.staff_link.value


class LinkIdentityOut(BaseModel):
    id: str
    channel: str
    channel_user_id: str
    customer_id: str
    method: str


@router.get("/customer-genome/repeat-buyers")
async def list_repeat_buyers(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    name: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
) -> Page[RepeatBuyerOut]:
    """The Repeat Buyers list: customers with two or more qualifying orders.

    Sorted by most recent purchase, so the customers worth contacting are at the top.
    """
    buyers, next_cursor = await repeat_buyers(
        session,
        business_id=principal.business_id,
        limit=limit,
        cursor=cursor,
        name_contains=name,
        since=since,
    )
    return Page[RepeatBuyerOut](
        items=[
            RepeatBuyerOut(
                id=str(buyer.customer_id),
                name=buyer.name,
                phone_e164=buyer.phone_e164,
                email_normalised=buyer.email_normalised,
                order_count=buyer.order_count,
                total_spend=str(buyer.total_spend),
                currency=buyer.currency,
                last_purchase_at=(
                    buyer.last_purchase_at.isoformat() if buyer.last_purchase_at else None
                ),
                history_url=f"/customers/{buyer.customer_id}/history",
            )
            for buyer in buyers
        ],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/customers/{customer_id}/history")
async def get_customer_history(
    customer_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    product_id: uuid.UUID | None = Query(default=None),
) -> CustomerHistoryOut:
    """A customer's order timeline, with date and product filters (CG-02)."""
    customer = await session.scalar(
        select(Customer).where(
            Customer.business_id == principal.business_id,
            Customer.id == customer_id,
        )
    )
    if customer is None:
        raise NotFound("No such customer.")

    figures = await customer_figures(
        session, business_id=principal.business_id, customer_id=customer_id
    )
    page = await customer_history(
        session,
        business_id=principal.business_id,
        customer_id=customer_id,
        limit=limit,
        cursor=cursor,
        since=since,
        until=until,
        product_id=product_id,
    )

    return CustomerHistoryOut(
        customer_id=str(customer_id),
        name=customer.name,
        order_count=figures.order_count,
        total_spend=str(figures.total_spend),
        currency=figures.currency,
        last_purchase_at=(
            figures.last_purchase_at.isoformat() if figures.last_purchase_at else None
        ),
        data_as_of=figures.data_as_of.isoformat(),
        items=[
            HistoryEntryOut(
                id=entry.order_id,
                source_order_id=entry.source_order_id,
                ordered_at=entry.ordered_at.isoformat(),
                status=entry.status,
                qualifying=entry.qualifying,
                total_amount=str(entry.total_amount),
                refund_amount=str(entry.refund_amount),
                currency=entry.currency,
                items=[
                    HistoryItemOut(
                        product_id=item["product_id"],
                        variant_id=item["variant_id"],
                        product_name=item["product_name"],
                        quantity=item["quantity"],
                        line_total=item["line_total"],
                    )
                    for item in entry.items
                ],
            )
            for entry in page.entries
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.post("/customers/{customer_id}/link-identity", status_code=201)
async def link_identity(
    customer_id: uuid.UUID,
    body: LinkIdentityRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> LinkIdentityOut:
    """Link a channel identity to a customer — the staff "Link customer" action.

    Re-linking the same identity to the same customer is a no-op. Linking it to a
    *different* customer raises a conflict rather than overwriting the first link.
    """
    customer = await session.scalar(
        select(Customer).where(
            Customer.business_id == principal.business_id,
            Customer.id == customer_id,
        )
    )
    if customer is None:
        raise NotFound("No such customer.")

    method = (
        IdentityMethod(body.method)
        if body.method in {m.value for m in IdentityMethod}
        else IdentityMethod.staff_link
    )
    row = await link(
        session,
        business_id=principal.business_id,
        channel=body.channel,
        channel_user_id=body.channel_user_id,
        customer_id=customer_id,
        method=method,
        verified_by_user_id=principal.user_id,
    )
    await session.commit()

    return LinkIdentityOut(
        id=str(row.id),
        channel=row.channel,
        channel_user_id=row.channel_user_id,
        customer_id=str(row.customer_id),
        method=row.method,
    )
