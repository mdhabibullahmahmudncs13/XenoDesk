"""The Restore Product HTTP surface and detection worker (RP-02…RP-10).

What these tests pin, in the order the feature runs:

- the waiting list is grouped by variant and never mixed (RP-03);
- the preview marks an unconsented customer as skipped and warns on low stock (RP-06, RP-09);
- confirming queues the eligible only, needs an Idempotency-Key, and is Owner-only
  (RP-07, RP-08);
- a repeat confirmation produces no second message (RP-08);
- detection writes an event and a notification, and **nothing** to the send path (RP-04);
- the delivery history reports queued and skipped recipients (RP-10);
- another tenant's event is not found.
"""

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer, Product, ProductVariant
from xenovarients.models.messaging import ContactPermission
from xenovarients.models.outbound import MessageTemplate, OutboundMessage
from xenovarients.models.platform import Notification
from xenovarients.models.restock import ProductInterest, RestockBatch, RestockEvent
from xenovarients.models.tenancy import AuditLog, Business
from xenovarients.platform.restock import detect_restocks
from xenovarients.platform.source import (
    SourceFixtures,
    SourceProduct,
    SourceVariant,
    StubSource,
)

pytestmark = pytest.mark.integration

TEMPLATE_BODY = "Hi {{customer_name}}, {{product_name}} is back at {{business_name}}."


@pytest_asyncio.fixture(loop_scope="session")
async def cleanup_batches(session: AsyncSession, users_and_memberships):
    """Delete this module's batches before the user fixture deletes its users.

    ``restock_batches.approved_by_user_id`` is ON DELETE RESTRICT, and the user
    fixture tears down *before* the business fixture that would otherwise cascade the
    batches away. Without this, the teardown fails after a confirming test.

    The delete is plain SQL, with the RLS variable set transaction-local: teardown
    runs outside the test's binding, and the ORM tenant filter cannot build a DELETE
    predicate (it only handles SELECT and UPDATE).
    """
    # Read the ids before teardown: the rollback below expires the ORM rows, and
    # reading an expired attribute afterwards needs IO outside the greenlet context.
    business_ids = {membership.business_id for membership in users_and_memberships[2:]}
    yield
    await session.rollback()
    for business_id in business_ids:
        await session.execute(
            text("SELECT set_config('app.business_id', :b, true)"),
            {"b": str(business_id)},
        )
        await session.execute(
            text("DELETE FROM restock_batches WHERE business_id = :b"),
            {"b": str(business_id)},
        )
        await session.commit()


async def _token(client: AsyncClient, email: str = "owner@example.com") -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


async def _seed(
    session: AsyncSession,
    business: Business,
    bind,
    *,
    stock_after: int = 5,
    consent_second: bool = True,
    template_body: str = TEMPLATE_BODY,
) -> dict[str, Any]:
    """One product+variant, two waiting customers, a template and a restock event."""
    await bind(business.id)

    first = Customer(
        business_id=business.id,
        source_customer_id=f"src-{uuid.uuid4().hex[:8]}",
        name="Ayesha",
        email_normalised="ayesha@example.com",
        phone_e164="+8801700000001",
    )
    second = Customer(
        business_id=business.id,
        source_customer_id=f"src-{uuid.uuid4().hex[:8]}",
        name="Tanvir",
        email_normalised="tanvir@example.com",
        phone_e164="+8801700000002",
    )
    session.add_all([first, second])
    await session.flush()

    product = Product(
        business_id=business.id,
        source_product_id=f"prod-{uuid.uuid4().hex[:8]}",
        name="Kurta",
    )
    session.add(product)
    await session.flush()

    variant = ProductVariant(
        business_id=business.id,
        product_id=product.id,
        source_variant_id=f"var-{uuid.uuid4().hex[:8]}",
        name="Red / M",
        is_available=True,
        stock_on_hand=stock_after,
    )
    session.add(variant)
    await session.flush()

    interests = [
        ProductInterest(
            business_id=business.id,
            customer_id=first.id,
            product_id=product.id,
            variant_id=variant.id,
            requested_at=datetime.now(UTC),
            contact_channel="email",
            contact_value=first.email_normalised,
            source="staff",
        ),
        ProductInterest(
            business_id=business.id,
            customer_id=second.id,
            product_id=product.id,
            variant_id=variant.id,
            requested_at=datetime.now(UTC),
            contact_channel="email",
            contact_value=second.email_normalised,
            source="staff",
        ),
    ]
    session.add_all(interests)
    session.add(
        ContactPermission(
            business_id=business.id,
            customer_id=first.id,
            channel="email",
            contact_value=first.email_normalised,
            eligible=True,
            source="staff",
            purposes=["restock"],
        )
    )
    if consent_second:
        session.add(
            ContactPermission(
                business_id=business.id,
                customer_id=second.id,
                channel="email",
                contact_value=second.email_normalised,
                eligible=True,
                source="staff",
                purposes=["restock"],
            )
        )

    template = MessageTemplate(
        business_id=business.id,
        key="restock",
        locale="en",
        body=template_body,
        version=1,
    )
    session.add(template)
    await session.flush()

    event = RestockEvent(
        business_id=business.id,
        product_id=product.id,
        variant_id=variant.id,
        detected_at=datetime.now(UTC),
        stock_after=stock_after,
        source="poll",
        source_ref=f"seed-{uuid.uuid4().hex[:8]}",
    )
    session.add(event)
    await session.commit()

    return {
        "business": business,
        "customers": (first, second),
        "product": product,
        "variant": variant,
        "template": template,
        "event": event,
    }


@pytest.mark.asyncio
async def test_waiting_list_groups_by_variant_and_never_mixes(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """RP-03: two variants of one product are two lists with two counts."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind)

    other_variant = ProductVariant(
        business_id=business.id,
        product_id=seeded["product"].id,
        source_variant_id=f"var-{uuid.uuid4().hex[:8]}",
        name="Blue / L",
        is_available=True,
        stock_on_hand=2,
    )
    session.add(other_variant)
    await session.flush()
    session.add(
        ProductInterest(
            business_id=business.id,
            customer_id=seeded["customers"][0].id,
            product_id=seeded["product"].id,
            variant_id=other_variant.id,
            requested_at=datetime.now(UTC),
            contact_channel="email",
            contact_value="ayesha@example.com",
            source="staff",
        )
    )
    await session.commit()

    token = await _token(client)
    response = await client.get(
        "/api/v1/customer-genome/product-interests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    groups = response.json()["items"]

    assert len(groups) == 2
    counts = {group["variant_name"]: group["waiting_count"] for group in groups}
    assert counts == {"Red / M": 2, "Blue / L": 1}
    for group in groups:
        assert {entry["customer_name"] for entry in group["entries"]} <= {"Ayesha", "Tanvir"}
        assert len(group["entries"]) == group["waiting_count"]


@pytest.mark.asyncio
async def test_the_preview_skips_a_customer_without_consent(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """RP-06, RP-08: the preview says who can be reached and who cannot, and why."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind, consent_second=False)

    token = await _token(client)
    response = await client.get(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/preview",
        params={"template_id": str(seeded["template"].id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["waiting_count"] == 2
    assert body["eligible_count"] == 1
    assert body["skipped_count"] == 1
    assert body["stock_warning"] is None

    eligible = [row for row in body["recipients"] if row["eligible"]]
    skipped = [row for row in body["recipients"] if not row["eligible"]]
    assert eligible[0]["channel"] == "email"
    assert "Kurta" in eligible[0]["message"]
    assert "Business One" in eligible[0]["message"]
    assert eligible[0]["skip_reason"] is None
    assert skipped[0]["skip_reason"] == "no_consent"


@pytest.mark.asyncio
async def test_the_preview_warns_when_stock_is_below_demand(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """RP-09: the numbers are shown and nothing is promised."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind, stock_after=1)

    token = await _token(client)
    response = await client.get(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/preview",
        params={"template_id": str(seeded["template"].id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    warning = response.json()["stock_warning"]

    assert warning is not None
    assert warning["stock_after"] == 1
    assert warning["waiting_demand"] == 2
    assert "not reserved" in warning["message"].lower()


@pytest.mark.asyncio
async def test_a_reservation_template_is_refused_at_preview(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """RP-09: the platform cannot reserve stock, so it must not promise to."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(
        session,
        business,
        bind,
        template_body="Hi {{customer_name}}, your {{product_name}} is set aside.",
    )

    token = await _token(client)
    response = await client.get(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/preview",
        params={"template_id": str(seeded["template"].id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "bad_request"


@pytest.mark.asyncio
async def test_confirming_queues_the_eligible_only_and_replays(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
    cleanup_batches,
):
    """RP-07, RP-08: one message for the eligible, a recorded skip for the rest."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind, consent_second=False)

    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "confirm-once"}
    payload = {"template_id": str(seeded["template"].id)}

    first = await client.post(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/notifications",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["queued"] == 1
    assert first.json()["skipped"] == [
        {"customer_id": str(seeded["customers"][1].id), "reason": "no_permission"}
    ]

    second = await client.post(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/notifications",
        json=payload,
        headers=headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["batch_id"] == first.json()["batch_id"]
    assert second.headers.get("Idempotent-Replay") == "true"

    await bind(business.id)
    batches = (await session.execute(select(RestockBatch))).scalars().all()
    messages = (await session.execute(select(OutboundMessage))).scalars().all()
    audits = (
        await session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "batch_approved")
        )
    ).scalar()

    assert len(batches) == 1
    assert len(messages) == 2  # one pending, one skipped — never two sends
    assert sorted(message.status for message in messages) == ["pending", "skipped"]
    assert audits == 1


@pytest.mark.asyncio
async def test_a_second_confirmation_key_cannot_duplicate_a_message(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
    cleanup_batches,
):
    """RP-08: the per-recipient key is the guarantee, not the header."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind, consent_second=False)

    token = await _token(client)
    url = f"/api/v1/customer-genome/restocks/{seeded['event'].id}/notifications"
    payload = {"template_id": str(seeded["template"].id)}

    first = await client.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "one"},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "two"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["queued"] == 0
    assert second.json()["duplicates"] == 2

    await bind(business.id)
    messages = (await session.execute(select(OutboundMessage))).scalars().all()
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_confirming_requires_an_idempotency_key(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """RP-07: the header is not optional on the endpoint that sends."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind)

    token = await _token(client)
    response = await client.post(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/notifications",
        json={"template_id": str(seeded["template"].id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400, response.text
    assert "Idempotency-Key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_confirming_is_owner_only(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """A staff member cannot approve a batch, even in their own business."""
    _owner, _staff, _membership, staff_membership = users_and_memberships
    business = await session.get(Business, staff_membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind)

    token = await _token(client, email="staff@example.com")
    response = await client.post(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/notifications",
        json={"template_id": str(seeded["template"].id)},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "staff-try"},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_detection_records_the_transition_and_sends_nothing(
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """RP-04: an event and a notification, and no route to a customer."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    await bind(business.id)

    product = Product(
        business_id=business.id,
        source_product_id=f"prod-{uuid.uuid4().hex[:8]}",
        name="Scarf",
    )
    session.add(product)
    await session.flush()
    variant = ProductVariant(
        business_id=business.id,
        product_id=product.id,
        source_variant_id=f"var-{uuid.uuid4().hex[:8]}",
        name="Green",
        is_available=False,
        stock_on_hand=0,
    )
    session.add(variant)
    await session.commit()

    source = StubSource(
        SourceFixtures(
            products=(
                SourceProduct(
                    source_product_id=product.source_product_id or "",
                    name="Scarf",
                    variants=(
                        SourceVariant(
                            source_variant_id=variant.source_variant_id or "",
                            source_product_id=product.source_product_id or "",
                            product_name="Scarf",
                            variant_name="Green",
                            is_available=True,
                            stock_on_hand=4,
                        ),
                    ),
                ),
            )
        )
    )
    moment = datetime.now(UTC)

    first = await detect_restocks(
        session, business_id=business.id, source=source, fetched_at=moment
    )
    await session.commit()
    second = await detect_restocks(
        session, business_id=business.id, source=source, fetched_at=moment
    )
    await session.commit()

    assert first.events_created == 1
    assert first.notifications_created == 1
    assert second.events_created == 0  # the same transition is not announced twice

    await bind(business.id)
    events = (await session.execute(select(RestockEvent))).scalars().all()
    notifications = (await session.execute(select(Notification))).scalars().all()
    messages = (await session.execute(select(OutboundMessage))).scalars().all()

    assert len(events) == 1
    assert events[0].stock_after == 4
    assert events[0].notified_owner_at is not None
    assert len(notifications) == 1
    assert messages == []


def test_the_detection_worker_has_no_send_path():
    """RP-04, asserted on the code itself: detection cannot reach the gateway."""
    source = inspect.getsource(detect_restocks)
    for forbidden in ("enqueue", "outbound", "dispatch", "OutboundMessage"):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_the_delivery_history_reports_each_recipient(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
    cleanup_batches,
):
    """RP-10: pending and skipped, each with its reason."""
    _owner, _staff, membership, _ = users_and_memberships
    business = await session.get(Business, membership.business_id)
    assert business is not None
    seeded = await _seed(session, business, bind, consent_second=False)

    token = await _token(client)
    url = f"/api/v1/customer-genome/restocks/{seeded['event'].id}/notifications"
    confirmed = await client.post(
        url,
        json={"template_id": str(seeded["template"].id)},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "history"},
    )
    assert confirmed.status_code == 201, confirmed.text

    history = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    assert history.status_code == 200, history.text
    items = history.json()["items"]

    assert len(items) == 2
    by_status = {item["status"]: item for item in items}
    assert set(by_status) == {"pending", "skipped"}
    assert by_status["skipped"]["skip_reason"] == "no_permission"
    assert by_status["pending"]["attempt_count"] == 0


@pytest.mark.asyncio
async def test_another_business_restock_event_is_not_found(
    client: AsyncClient,
    session: AsyncSession,
    users_and_memberships,
    bind,
):
    """The tenant comes from the token; another business's event is a 404."""
    _owner, _staff, _membership, staff_membership = users_and_memberships
    other_business = await session.get(Business, staff_membership.business_id)
    assert other_business is not None
    seeded = await _seed(session, other_business, bind)

    token = await _token(client)  # the owner of business one
    response = await client.get(
        f"/api/v1/customer-genome/restocks/{seeded['event'].id}/preview",
        params={"template_id": str(seeded["template"].id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404, response.text
