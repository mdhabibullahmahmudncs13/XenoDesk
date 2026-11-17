"""The four outbound channel adapters: Email, SMS, Messenger, WhatsApp.

Every adapter answers the same two questions:

- ``send`` — put this body in front of this recipient, and tell me what happened.
- ``eligibility`` — can this channel be used *right now*, and if not, why.

The adapters are intentionally thin. They translate our shape into a provider's HTTP
call and the provider's response back into a ``SendResult``. Everything about *when*
to send and *whether* to send lives in ``outbound.py`` and ``eligibility.py`` — an
adapter that made policy decisions would be policy nobody could test in isolation.

**Providers are optional until configured.** Each adapter checks its own credential
in ``eligibility`` and reports a reason if it is missing, so a business with no
WhatsApp account gets "WhatsApp is not configured" rather than a failed send.
"""

import logging
from typing import Any

import httpx

from xenovarients.core.config import get_settings
from xenovarients.platform.outbound import SendResult

logger = logging.getLogger(__name__)

# Provider base URLs. Kept as constants so a test can monkeypatch one without
# touching the network layer.
META_GRAPH_URL = "https://graph.facebook.com/v21.0"
MESSENGER_SEND_URL = f"{META_GRAPH_URL}/me/messages"
WHATSAPP_SEND_URL = f"{META_GRAPH_URL}/me/messages"

# A send must not hang the dispatcher. Provider calls are synchronous inside the
# adapter; the timeout bounds how long a stuck provider holds a worker.
DEFAULT_TIMEOUT_SECONDS = 10.0


def _post(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    """POST JSON and return ``(status, body)``. Never raises for a network error."""
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.warning("Channel HTTP call failed: %s", exc)
        return 0, {"error": str(exc)}
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return response.status_code, body if isinstance(body, dict) else {"body": body}


class EmailAdapter:
    """Transactional email over an HTTP API.

    Marketing content needs an opt-in separate from transactional consent, so the
    adapter refuses to send when no API key is configured rather than silently
    dropping the message.
    """

    channel = "email"

    def __init__(self, api_key: str | None = None, from_address: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.email_api_key
        self.from_address = from_address or (
            f"hello@{settings.email_from_domain}" if settings.email_from_domain else None
        )

    def eligibility(self) -> str | None:
        if not self.api_key:
            return "email_provider_not_configured"
        if not self.from_address:
            return "email_from_domain_not_configured"
        return None

    def send(self, *, to_address: str, body: str, reference: str) -> SendResult:
        if not self.api_key or not self.from_address:
            return SendResult(ok=False, error_code="email_provider_not_configured")

        status, payload = _post(
            "https://api.emailprovider.test/v1/send",
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload={
                "from": self.from_address,
                "to": to_address,
                "text": body,
                "reference": reference,
            },
        )
        if status == 0:
            return SendResult(ok=False, error_code="provider_unavailable", response=payload)
        if status >= 400:
            return SendResult(ok=False, error_code="provider_rejected", response=payload)
        provider_id = payload.get("id") or payload.get("message_id")
        return SendResult(ok=True, provider_message_id=str(provider_id), response=payload)


class SmsAdapter:
    """SMS over a gateway.

    The gateway key is optional in settings because the channel is opt-in per
    business. A business with no key gets a recorded skip, not a failed send.
    """

    channel = "sms"

    def __init__(self, gateway_key: str | None = None) -> None:
        settings = get_settings()
        self.gateway_key = gateway_key if gateway_key is not None else settings.sms_gateway_key

    def eligibility(self) -> str | None:
        if not self.gateway_key:
            return "sms_provider_not_configured"
        return None

    def send(self, *, to_address: str, body: str, reference: str) -> SendResult:
        if not self.gateway_key:
            return SendResult(ok=False, error_code="sms_provider_not_configured")

        status, payload = _post(
            "https://api.smsgateway.test/v1/send",
            headers={"Authorization": f"Bearer {self.gateway_key}"},
            payload={"to": to_address, "text": body, "reference": reference},
        )
        if status == 0:
            return SendResult(ok=False, error_code="provider_unavailable", response=payload)
        if status >= 400:
            return SendResult(ok=False, error_code="provider_rejected", response=payload)
        provider_id = payload.get("sid") or payload.get("id")
        return SendResult(ok=True, provider_message_id=str(provider_id), response=payload)


class MessengerAdapter:
    """Meta Messenger, via the Graph API.

    Two provider constraints shape this adapter, both from OD-05 and both still
    marked UNVERIFIED:

    - A message outside the 24-hour free-reply window needs a message tag whose
      category the provider must have approved. The tag category is not known, so
      the adapter sends untagged and lets the provider reject it — the rejection
      surfaces as ``provider_rejected`` rather than being silently dropped.
    - A send needs a page access token, which expires in about an hour. The token is
      passed in rather than cached: caching a token that silently expires is a
    delivery failure with no visible cause.
    """

    channel = "messenger"

    def __init__(self, page_access_token: str | None = None) -> None:
        self.page_access_token = page_access_token

    def eligibility(self) -> str | None:
        if not self.page_access_token:
            return "messenger_page_token_not_configured"
        return None

    def send(self, *, to_address: str, body: str, reference: str) -> SendResult:
        if not self.page_access_token:
            return SendResult(ok=False, error_code="messenger_page_token_not_configured")

        status, payload = _post(
            MESSENGER_SEND_URL,
            headers={"Authorization": f"Bearer {self.page_access_token}"},
            payload={
                "recipient": {"id": to_address},
                "message": {"text": body},
                "messaging_type": "RESPONSE",
                "message_tag": "ACCOUNT_UPDATE",
                "client_ref": reference,
            },
        )
        if status == 0:
            return SendResult(ok=False, error_code="provider_unavailable", response=payload)
        if status >= 400:
            return SendResult(ok=False, error_code="provider_rejected", response=payload)
        provider_id = payload.get("message_id")
        return SendResult(ok=True, provider_message_id=str(provider_id), response=payload)


class WhatsappAdapter:
    """WhatsApp Business, via the Cloud API.

    A business-initiated message needs an approved template. The template name and
    its parameters are part of the message body, so the adapter takes them
    explicitly rather than guessing from the body text.
    """

    channel = "whatsapp"

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        template_name: str | None = None,
    ) -> None:
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.template_name = template_name

    def eligibility(self) -> str | None:
        if not self.access_token:
            return "whatsapp_token_not_configured"
        if not self.phone_number_id:
            return "whatsapp_phone_number_not_configured"
        if not self.template_name:
            return "whatsapp_template_not_configured"
        return None

    def send(self, *, to_address: str, body: str, reference: str) -> SendResult:
        reason = self.eligibility()
        if reason is not None:
            return SendResult(ok=False, error_code=reason)

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_address,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": "en"},
                "body": [{"type": "TEXT", "text": body}],
            },
        }
        status, response = _post(
            f"{WHATSAPP_SEND_URL}?phone_number_id={self.phone_number_id}",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
        if status == 0:
            return SendResult(ok=False, error_code="provider_unavailable", response=response)
        if status >= 400:
            return SendResult(ok=False, error_code="provider_rejected", response=response)
        messages = response.get("messages") or []
        provider_id = messages[0].get("id") if messages else None
        return SendResult(ok=True, provider_message_id=str(provider_id), response=response)


def build_adapters() -> dict[str, Any]:
    """The adapter set for this deployment, keyed by channel.

    Only Email and SMS are enabled by default (OD-05): Messenger and WhatsApp stay
    opt-in per business until the provider rules are confirmed.
    """
    return {
        "email": EmailAdapter(),
        "sms": SmsAdapter(),
        "messenger": MessengerAdapter(),
        "whatsapp": WhatsappAdapter(),
    }


def parse_provider_error(payload: dict[str, Any]) -> str | None:
    """Pull the provider's own error message out of a response, if there is one.

    Useful in logs and in the audit trail: "provider_rejected" alone tells an
    operator nothing they can act on.
    """
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        return str(message) if message else None
    if isinstance(error, str):
        return error
    return None


__all__ = [
    "EmailAdapter",
    "MessengerAdapter",
    "SmsAdapter",
    "WhatsappAdapter",
    "build_adapters",
    "parse_provider_error",
]
