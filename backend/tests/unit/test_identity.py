"""Identity resolution ladder and contact permissions (CG-03, CG-10).

The rule under test throughout: a name is never a matching key, and a conflict is
recorded rather than merged.
"""

import pytest

from xenovarients.platform.identity import (
    IdentityAlreadyLinked,
    ResolveOutcome,
    check_permission,
    grant_permission,
    link,
    normalise_email,
    normalise_phone,
    resolve,
    revoke_permission,
    unlink,
)


def test_normalise_phone_converts_bangladeshi_numbers():
    assert normalise_phone("01712345678") == "+8801712345678"
    assert normalise_phone("+8801712345678") == "+8801712345678"
    assert normalise_phone("8801712345678") == "+8801712345678"


def test_normalise_phone_does_not_invent_a_country_code():
    """A number that is not Bangladeshi keeps its digits; a guess is worse than a miss."""
    assert normalise_phone("+14155552671") == "+14155552671"


def test_normalise_email_lowercases_and_strips():
    assert normalise_email("  Owner@Example.COM ") == "owner@example.com"


@pytest.mark.asyncio
async def test_resolve_with_no_link_and_no_match(session, businesses, bind):
    """An unknown Messenger identity resolves to no-match and raises nothing."""
    business_one, _ = businesses
    await bind(business_one.id)

    result = await resolve(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="unknown-person",
    )
    assert result.outcome == ResolveOutcome.no_match
    assert result.customer_id is None


@pytest.mark.asyncio
async def test_resolve_matches_by_phone(session, businesses, customer_factory, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, phone_e164="+8801712345678")

    result = await resolve(
        session,
        business_id=business_one.id,
        channel="sms",
        channel_user_id="+8801712345678",
    )
    assert result.outcome == ResolveOutcome.matched
    assert result.customer_id == customer.id


@pytest.mark.asyncio
async def test_verified_link_wins_over_phone(session, businesses, customer_factory, bind):
    """A confirmed link outranks an inferred match — the ladder's first rung."""
    business_one, _ = businesses
    await bind(business_one.id)
    linked = await customer_factory(business_one, phone_e164="+8801712345678")
    by_phone = await customer_factory(business_one, phone_e164="+8801712345678")

    await link(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="m-1",
        customer_id=linked.id,
    )
    await session.commit()

    result = await resolve(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="m-1",
        phone_e164="+8801712345678",
    )
    assert result.outcome == ResolveOutcome.matched
    assert result.customer_id == linked.id
    assert result.customer_id != by_phone.id


@pytest.mark.asyncio
async def test_multiple_phone_matches_are_a_conflict_not_a_merge(
    session, businesses, customer_factory, bind
):
    """Two customers share a phone number. The system must not pick one."""
    business_one, _ = businesses
    await bind(business_one.id)
    await customer_factory(business_one, phone_e164="+8801712345678")
    await customer_factory(business_one, phone_e164="+8801712345678")
    await session.commit()

    result = await resolve(
        session,
        business_id=business_one.id,
        channel="sms",
        channel_user_id="+8801712345678",
    )
    assert result.outcome == ResolveOutcome.conflict
    assert result.conflict_id is not None
    assert len(result.candidates) == 2


@pytest.mark.asyncio
async def test_link_is_idempotent_for_the_same_customer(
    session, businesses, customer_factory, bind
):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one)

    first = await link(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="m-1",
        customer_id=customer.id,
    )
    second = await link(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="m-1",
        customer_id=customer.id,
    )
    await session.commit()
    assert first.id == second.id


@pytest.mark.asyncio
async def test_link_to_a_second_customer_is_refused(session, businesses, customer_factory, bind):
    """Overwriting an existing link would move one customer's history to another."""
    business_one, _ = businesses
    await bind(business_one.id)
    first = await customer_factory(business_one)
    second = await customer_factory(business_one)

    await link(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="m-1",
        customer_id=first.id,
    )
    await session.commit()

    with pytest.raises(IdentityAlreadyLinked):
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="m-1",
            customer_id=second.id,
        )
    await session.rollback()


@pytest.mark.asyncio
async def test_unlink_removes_the_link(session, businesses, customer_factory, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one)
    await link(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="m-1",
        customer_id=customer.id,
    )
    await session.commit()

    assert await unlink(
        session, business_id=business_one.id, channel="messenger", channel_user_id="m-1"
    )
    await session.commit()
    assert not await unlink(
        session, business_id=business_one.id, channel="messenger", channel_user_id="m-1"
    )


@pytest.mark.asyncio
async def test_consent_is_per_purpose(session, businesses, customer_factory, bind):
    """Consent for a review request is not consent for an ad (OD-07)."""
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one)

    await grant_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="email",
        contact_value="c@example.com",
        source="review_reply",
        purposes=["review_request"],
    )
    await session.commit()

    assert await check_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="email",
        purpose="review_request",
    )
    assert not await check_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="email",
        purpose="own_ads_promotion",
    )


@pytest.mark.asyncio
async def test_opt_out_is_sticky(session, businesses, customer_factory, bind):
    """An opt-out must survive; it cannot be cleared by re-granting eligibility."""
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one)

    await grant_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="sms",
        contact_value="+8801712345678",
        source="manual",
        purposes=["restock_notification"],
    )
    await session.commit()

    assert await revoke_permission(
        session, business_id=business_one.id, customer_id=customer.id, channel="sms"
    )
    await session.commit()

    assert not await check_permission(
        session, business_id=business_one.id, customer_id=customer.id, channel="sms"
    )
    # Revoking again is a no-op, not an error.
    assert not await revoke_permission(
        session, business_id=business_one.id, customer_id=customer.id, channel="sms"
    )


@pytest.mark.asyncio
async def test_identity_resolution_is_tenant_scoped(session, businesses, customer_factory, bind):
    """A link in one business must not resolve in another."""
    business_one, business_two = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one)
    await link(
        session,
        business_id=business_one.id,
        channel="messenger",
        channel_user_id="shared-id",
        customer_id=customer.id,
    )
    await session.commit()

    await bind(business_two.id)
    result = await resolve(
        session,
        business_id=business_two.id,
        channel="messenger",
        channel_user_id="shared-id",
    )
    assert result.outcome == ResolveOutcome.no_match


@pytest.mark.asyncio
async def test_permission_check_is_tenant_scoped(session, businesses, customer_factory, bind):
    business_one, business_two = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one)
    await grant_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="email",
        contact_value="c@example.com",
        source="manual",
        purposes=["review_request"],
    )
    await session.commit()

    await bind(business_two.id)
    assert not await check_permission(
        session, business_id=business_two.id, customer_id=customer.id, channel="email"
    )
