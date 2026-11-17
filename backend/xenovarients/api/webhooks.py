"""Inbound webhook endpoints.

These are the only endpoints without an auth header. The provider's signature *is*
the authentication, so the path carries the business id and the request body carries
the proof.

The response is ``202 Accepted`` with ``{received, duplicate}``. Processing happens
after the response — a provider that waits for slow processing will time out and
retry, and the retry must not create a second event.
"""

import uuid

from fastapi import APIRouter, Header, Request, Response

from xenovarients.api.errors import BadRequest, NotFound, Unauthorized
from xenovarients.db.session import SessionLocal
from xenovarients.db.tenant import (
    bind_tenant,
    clear_tenant,
    install_tenant_filter,
    reset_tenant,
)
from xenovarients.models.tenancy import Business
from xenovarients.platform.inbound import (
    ChannelWebhookAdapter,
    GenericJsonAdapter,
    MetaWebhookAdapter,
    ingest,
)
from xenovarients.platform.webhooks import SignatureError

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ADAPTERS: dict[str, ChannelWebhookAdapter] = {
    "messenger": MetaWebhookAdapter(),
    "generic": GenericJsonAdapter(),
}


@router.post("/messaging/{channel}/{business_id}", status_code=202)
async def receive_messaging_webhook(
    channel: str,
    business_id: uuid.UUID,
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> Response:
    """Accept an inbound messaging event.

    The business id is in the path so the receiver can look up the webhook secret and
    route the event to the right tenant.
    """
    adapter = ADAPTERS.get(channel)
    if adapter is None:
        raise NotFound(f"No inbound adapter for channel '{channel}'.")

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if x_signature:
        headers["x-signature"] = x_signature
    if x_timestamp:
        headers["x-timestamp"] = x_timestamp
    if x_hub_signature_256:
        headers["x-hub-signature-256"] = x_hub_signature_256

    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            business = await session.get(Business, business_id)
            if business is None:
                raise NotFound("Business not found.")
            secret = business.webhook_secret
            if not secret:
                raise Unauthorized("This business has no webhook secret configured.")

            # The event lands in a tenant-scoped table, so both isolation layers must
            # be bound to this business before the write. Without the Postgres session
            # variable the RLS policy rejects the insert — which is the point.
            await bind_tenant(session, str(business_id))

            try:
                stored, duplicate = await ingest(
                    session,
                    business_id=business_id,
                    adapter=adapter,
                    body=body,
                    headers=headers,
                    secret=secret,
                )
            except SignatureError as exc:
                raise Unauthorized(str(exc)) from exc
            except ValueError as exc:
                raise BadRequest("Webhook payload is malformed.") from exc
        finally:
            await session.rollback()
            await clear_tenant(session)
            reset_tenant()

    return Response(
        status_code=202,
        content=f'{{"received": true, "duplicate": {"true" if duplicate else "false"}, '
        f'"stored": {stored}}}',
        media_type="application/json",
    )


@router.get("/messaging/{channel}/{business_id}", status_code=200)
async def messaging_webhook_verify(
    channel: str,
    business_id: uuid.UUID,
    request: Request,
) -> Response:
    """Provider handshake: echo the challenge so the provider can verify the URL."""
    params = dict(request.query_params)
    challenge = params.get("hub.challenge") or params.get("challenge")
    if challenge is None:
        raise BadRequest("Missing challenge parameter.")
    return Response(content=challenge, media_type="text/plain")
