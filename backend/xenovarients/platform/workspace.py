"""Agent Workspace normalisation, matching, routing, and read-only tools."""

import re
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.ads import AdInsightSnapshot
from xenovarients.models.customer import CustomerOrder, OrderStatus
from xenovarients.models.workspace import FaqAlias, FaqEntry

TOOL_REGISTRY = {
    "active_ads_count": "Read the count of active own ads.",
    "qualifying_orders_count": "Read the count of qualifying orders.",
}
BLOCKED_INTENTS = re.compile(r"\b(delete|remove|update|change|send|publish|refund)\b", re.I)


class LLMPort(Protocol):
    async def answer(self, prompt: str) -> tuple[str, int, int]:
        """Return answer, input tokens, and output tokens."""


class StubLLM:
    async def answer(self, prompt: str) -> tuple[str, int, int]:
        return "I could not find a verified answer in the connected data.", 0, 0


def normalise(value: str) -> str:
    value = unicodedata.normalize("NFC", value).lower()
    value = value.translate(str.maketrans({"0": "o", "1": "i", "3": "e"}))
    value = re.sub(r"[^a-z0-9\u0980-\u09ff\s]", " ", value)
    return " ".join(value.split())


async def match_faq(session: AsyncSession, *, business_id: Any, question: str) -> FaqEntry | None:
    key = normalise(question)
    entry = await session.scalar(
        select(FaqEntry).where(
            FaqEntry.business_id == business_id,
            FaqEntry.is_active.is_(True),
            FaqEntry.faq_key == key,
        )
    )
    if entry is not None:
        return entry
    aliases = (
        await session.execute(
            select(FaqAlias, FaqEntry)
            .join(FaqEntry, FaqEntry.id == FaqAlias.faq_entry_id)
            .where(FaqAlias.business_id == business_id, FaqEntry.is_active.is_(True))
        )
    ).all()
    for alias, candidate in aliases:
        if normalise(alias.alias) == key:
            return candidate
    best: tuple[float, FaqEntry | None] = (0.0, None)
    for alias, candidate in aliases:
        score = SequenceMatcher(None, normalise(alias.alias), key).ratio()
        if score > best[0]:
            best = (score, candidate)
    return best[1] if best[0] >= 0.8 else None


async def run_read_tool(
    session: AsyncSession, *, business_id: Any, name: str
) -> dict[str, Any]:
    if name not in TOOL_REGISTRY:
        raise ValueError("Tool is not allow-listed.")
    if name == "active_ads_count":
        value = await session.scalar(
            select(func.count(AdInsightSnapshot.id)).where(
                AdInsightSnapshot.business_id == business_id,
                AdInsightSnapshot.scope == "own",
            )
        )
    else:
        value = await session.scalar(
            select(func.count(CustomerOrder.id)).where(
                CustomerOrder.business_id == business_id,
                CustomerOrder.status.in_(
                    [OrderStatus.paid.value, OrderStatus.completed.value]
                ),
            )
        )
    return {"tool": name, "value": int(value or 0), "data_as_of": datetime.now(UTC)}


def blocked_intent(question: str) -> bool:
    return bool(BLOCKED_INTENTS.search(question))
