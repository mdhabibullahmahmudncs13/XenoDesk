"""The four outbound channel adapters.

Nothing here touches the network: ``_post`` is monkeypatched, so a test failure
means the adapter's logic is wrong, not that a provider is down.
"""

from typing import Any

import pytest

from xenovarients.platform import channels
from xenovarients.platform.channels import (
    EmailAdapter,
    MessengerAdapter,
    SmsAdapter,
    WhatsappAdapter,
    parse_provider_error,
)


@pytest.fixture
def posted(monkeypatch) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Capture POSTs instead of making them. Returns the captured calls."""
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def _fake_post(url, *, headers, payload, timeout=channels.DEFAULT_TIMEOUT_SECONDS):
        calls.append((url, headers, payload))
        return 200, {"id": "provider-1"}

    monkeypatch.setattr(channels, "_post", _fake_post)
    return calls


def test_email_requires_a_key() -> None:
    adapter = EmailAdapter(api_key=None, from_address="hello@example.com")
    assert adapter.eligibility() == "email_provider_not_configured"


def test_email_requires_a_from_address() -> None:
    adapter = EmailAdapter(api_key="key", from_address=None)
    assert adapter.eligibility() == "email_from_domain_not_configured"


def test_email_is_eligible_when_configured() -> None:
    adapter = EmailAdapter(api_key="key", from_address="hello@example.com")
    assert adapter.eligibility() is None


def test_email_sends(posted) -> None:
    adapter = EmailAdapter(api_key="key", from_address="hello@example.com")
    result = adapter.send(to_address="c@example.com", body="hi", reference="ref-1")

    assert result.ok is True
    assert result.provider_message_id == "provider-1"
    url, headers, payload = posted[0]
    assert headers["Authorization"] == "Bearer key"
    assert payload["to"] == "c@example.com"
    assert payload["text"] == "hi"
    assert payload["reference"] == "ref-1"


def test_email_reports_a_provider_rejection(monkeypatch) -> None:
    monkeypatch.setattr(channels, "_post", lambda *a, **k: (422, {"error": "bad address"}))
    adapter = EmailAdapter(api_key="key", from_address="hello@example.com")
    result = adapter.send(to_address="c@example.com", body="hi", reference="ref-1")

    assert result.ok is False
    assert result.error_code == "provider_rejected"


def test_email_reports_an_unreachable_provider(monkeypatch) -> None:
    monkeypatch.setattr(channels, "_post", lambda *a, **k: (0, {"error": "timeout"}))
    adapter = EmailAdapter(api_key="key", from_address="hello@example.com")
    result = adapter.send(to_address="c@example.com", body="hi", reference="ref-1")

    assert result.ok is False
    assert result.error_code == "provider_unavailable"


def test_sms_requires_a_gateway_key() -> None:
    assert SmsAdapter(gateway_key=None).eligibility() == "sms_provider_not_configured"


def test_sms_sends(posted) -> None:
    adapter = SmsAdapter(gateway_key="key")
    result = adapter.send(to_address="+8801712345678", body="hi", reference="ref-2")

    assert result.ok is True
    assert posted[0][2]["to"] == "+8801712345678"


def test_messenger_requires_a_page_token() -> None:
    assert MessengerAdapter(page_access_token=None).eligibility() == (
        "messenger_page_token_not_configured"
    )


def test_messenger_sends(posted) -> None:
    adapter = MessengerAdapter(page_access_token="token")
    result = adapter.send(to_address="user-1", body="hi", reference="ref-3")

    assert result.ok is True
    url, headers, payload = posted[0]
    assert headers["Authorization"] == "Bearer token"
    assert payload["recipient"]["id"] == "user-1"
    assert payload["message"]["text"] == "hi"


def test_whatsapp_requires_a_token() -> None:
    assert WhatsappAdapter(access_token=None).eligibility() == "whatsapp_token_not_configured"


def test_whatsapp_requires_a_phone_number_id() -> None:
    adapter = WhatsappAdapter(access_token="token", phone_number_id=None)
    assert adapter.eligibility() == "whatsapp_phone_number_not_configured"


def test_whatsapp_requires_a_template() -> None:
    adapter = WhatsappAdapter(access_token="token", phone_number_id="123", template_name=None)
    assert adapter.eligibility() == "whatsapp_template_not_configured"


def test_whatsapp_sends_a_template(posted) -> None:
    adapter = WhatsappAdapter(
        access_token="token", phone_number_id="123", template_name="review_request"
    )
    result = adapter.send(to_address="+8801712345678", body="hi", reference="ref-4")

    assert result.ok is True
    url, headers, payload = posted[0]
    assert "phone_number_id=123" in url
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "review_request"


def test_whatsapp_refuses_to_send_when_not_configured(posted) -> None:
    """An unconfigured channel reports ineligibility instead of making a call."""
    adapter = WhatsappAdapter(access_token=None)
    result = adapter.send(to_address="+8801712345678", body="hi", reference="ref-5")
    assert result.ok is False
    assert result.error_code == "whatsapp_token_not_configured"
    assert posted == []


def test_parse_provider_error_reads_a_nested_message() -> None:
    assert parse_provider_error({"error": {"message": "Invalid recipient"}}) == "Invalid recipient"


def test_parse_provider_error_handles_a_bare_string() -> None:
    assert parse_provider_error({"error": "boom"}) == "boom"


def test_parse_provider_error_returns_none_when_absent() -> None:
    assert parse_provider_error({"id": "x"}) is None
