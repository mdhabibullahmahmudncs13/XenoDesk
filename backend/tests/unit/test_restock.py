"""The pure parts of Restore Product: merge rendering and the RP-09 guard.

The database behaviour is covered in ``tests/integration/test_restock_api.py``. What
belongs here is what can be checked without a database: a merge field is filled, an
unknown one is visibly left alone, and a template that promises to reserve stock is
rejected (RP-09).
"""

import uuid

import pytest

from xenovarients.platform.restock import (
    MERGE_FIELDS,
    ReservationLanguageRejected,
    batch_key,
    outbound_key,
    render,
    validate_template,
)


def test_every_merge_field_is_filled():
    fields = {
        "customer_name": "Ayesha",
        "request_date": "2026-11-17",
        "product_name": "Kurta",
        "business_name": "Dhaka Threads",
    }
    body = " | ".join("{{" + key + "}}" for key in MERGE_FIELDS)
    assert render(body, fields) == " | ".join(fields[key] for key in MERGE_FIELDS)


def test_an_unknown_placeholder_is_left_visible():
    """A typo must show up in the preview, not vanish into a blank."""
    assert render("Hi {{custmer_name}}", {"customer_name": "Ayesha"}) == "Hi {{custmer_name}}"


def test_reservation_language_is_rejected():
    with pytest.raises(ReservationLanguageRejected):
        validate_template("Good news {{customer_name}}, your Kurta is set aside.")


def test_an_ordinary_restock_template_passes():
    validate_template("Hi {{customer_name}}, {{product_name}} is back in stock.")


def test_the_outbound_key_is_scoped_per_channel():
    """RP-08: business + event + interest + channel, so one interest can reach two channels."""
    event = uuid.uuid4()
    interest = uuid.uuid4()
    business = uuid.uuid4()

    email = outbound_key(
        business_id=business, restock_event_id=event, interest_id=interest, channel="email"
    )
    sms = outbound_key(
        business_id=business, restock_event_id=event, interest_id=interest, channel="sms"
    )

    assert email == outbound_key(
        business_id=business, restock_event_id=event, interest_id=interest, channel="email"
    )
    assert email != sms
    assert len(email) == 64


def test_the_batch_key_is_scoped_per_tenant():
    """The same client key in two businesses must not collide."""
    one = batch_key(business_id=uuid.uuid4(), request_key="key-1")
    two = batch_key(business_id=uuid.uuid4(), request_key="key-1")
    assert one != two
    assert len(one) == 64
