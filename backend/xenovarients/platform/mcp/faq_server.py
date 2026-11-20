"""The FAQ MCP server, over stdio.

This is the one server that runs as its own process, because it answers a single
support question and needs nothing from the API request cycle::

    XENODESK_BUSINESS_ID=<uuid> python -m xenovarients.platform.mcp.faq_server

The tenant comes from the environment and never from a tool argument — a client cannot
ask one business's FAQ table about another's. It only *reads* the FAQ registry; a
question with no verified answer says so instead of guessing.
"""

import os
import uuid
from typing import Any

from xenovarients.platform import workspace
from xenovarients.platform.mcp.shared import (
    ToolError,
    build_server,
    read_only,
    result,
    tenant_session,
)

ENV_BUSINESS_ID = "XENODESK_BUSINESS_ID"

server = build_server(
    name="faq",
    title="XenoDesk FAQ",
    instructions=(
        "Read-only answers to support questions from the business's FAQ registry. "
        "Returns the verified answer when one matches, and says so when none does. "
        "Never sends, edits or deletes anything."
    ),
)


def _business_id() -> uuid.UUID:
    value = os.environ.get(ENV_BUSINESS_ID, "").strip()
    if not value:
        raise ToolError(
            "not_configured",
            f"Set {ENV_BUSINESS_ID} to the business this server answers for.",
        )
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ToolError("not_configured", f"{ENV_BUSINESS_ID} is not a valid uuid.") from exc


@read_only(server)
async def match_faq(question: str) -> dict[str, Any]:
    """Find the verified FAQ answer that matches this question.

    Matching is the workspace's own normalisation (case, punctuation, Unicode) plus a
    similarity floor over the registered aliases. No match is ``matched: false`` — the
    tool never composes an answer of its own.
    """
    business_id = _business_id()
    if workspace.blocked_intent(question):
        return result(
            matched=False,
            blocked=True,
            reason="write_intent",
            detail="This server answers questions only; it cannot change anything.",
        )

    async with tenant_session(business_id) as session:
        entry = await workspace.match_faq(session, business_id=business_id, question=question)
        if entry is None:
            return result(matched=False, blocked=False, question=question)

        payload = {
            "faq_id": str(entry.id),
            "faq_key": entry.faq_key,
            "locale": entry.locale,
            "answer": entry.answer,
            "answer_type": entry.answer_type,
            "is_active": entry.is_active,
        }

    return result(matched=True, blocked=False, question=question, faq=payload)


def main() -> None:
    """Run the FAQ server over stdio."""
    server.run("stdio")


if __name__ == "__main__":  # pragma: no cover - process entry point
    main()
