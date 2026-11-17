"""Agent Workspace FAQ, chat, and tour endpoints."""

import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_principal, get_tenant_session, require_admin
from xenovarients.api.errors import BadRequest, NotFound
from xenovarients.models.workspace import (
    AiUsageEvent,
    AnswerType,
    ChatMessage,
    ChatRole,
    ChatSession,
    FaqAlias,
    FaqEntry,
    TourProgress,
    TourState,
    TourStep,
)
from xenovarients.platform.workspace import (
    StubLLM,
    blocked_intent,
    match_faq,
    normalise,
    run_read_tool,
)

router = APIRouter(prefix="/api/v1/agent-workspace", tags=["agent-workspace"])


class FaqIn(BaseModel):
    faq_key: str
    answer: str
    aliases: list[str] = []
    locale: str = "en"
    review_due_at: datetime | None = None


class FaqPatch(BaseModel):
    answer: str | None = None
    review_due_at: datetime | None = None
    is_active: bool | None = None


class FaqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    faq_key: str
    answer: str
    aliases: list[str]
    review_due_at: datetime
    stale: bool


class ChatIn(BaseModel):
    content: str
    image_attached: bool = False


class ChatOut(BaseModel):
    answer: str
    answer_type: str
    references: dict[str, Any]
    data_as_of: datetime
    usage: dict[str, Any]


class TourIn(BaseModel):
    step_order: int = Field(ge=1)
    target_id: str
    selector: str | None = None
    message: str
    locale: str = "en"


class TourStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_order: int
    target_id: str
    selector: str | None
    message: str
    locale: str
    is_active: bool


def _faq_out(entry: FaqEntry, aliases: list[str]) -> FaqOut:
    return FaqOut(
        id=entry.id,
        faq_key=entry.faq_key,
        answer=entry.answer,
        aliases=aliases,
        review_due_at=entry.review_due_at,
        stale=entry.review_due_at < datetime.now(UTC),
    )


@router.post("/faqs", response_model=FaqOut)
async def create_faq(
    body: FaqIn,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> FaqOut:
    entry = FaqEntry(
        business_id=principal.business_id,
        faq_key=normalise(body.faq_key),
        answer=body.answer,
        owner_user_id=principal.user_id,
        review_due_at=body.review_due_at or datetime.now(UTC) + timedelta(days=90),
        locale=body.locale,
    )
    session.add(entry)
    await session.flush()
    for alias in body.aliases:
        session.add(
            FaqAlias(
                business_id=principal.business_id,
                faq_entry_id=entry.id,
                alias=normalise(alias),
                locale=body.locale,
            )
        )
    await session.commit()
    return _faq_out(entry, [normalise(alias) for alias in body.aliases])


@router.get("/faqs")
async def list_faqs(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[FaqOut]:
    entries = (
        await session.execute(
            select(FaqEntry)
            .where(FaqEntry.business_id == principal.business_id)
            .order_by(FaqEntry.faq_key)
        )
    ).scalars()
    result = []
    for entry in entries:
        aliases = (
            await session.execute(
                select(FaqAlias.alias).where(FaqAlias.faq_entry_id == entry.id)
            )
        ).scalars()
        result.append(_faq_out(entry, list(aliases)))
    return result


@router.patch("/faqs/{faq_id}", response_model=FaqOut)
async def update_faq(
    faq_id: uuid.UUID,
    body: FaqPatch,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> FaqOut:
    entry = await session.scalar(
        select(FaqEntry).where(
            FaqEntry.id == faq_id,
            FaqEntry.business_id == principal.business_id,
        )
    )
    if entry is None:
        raise NotFound("No such FAQ.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await session.commit()
    aliases = (
        await session.execute(select(FaqAlias.alias).where(FaqAlias.faq_entry_id == entry.id))
    ).scalars()
    return _faq_out(entry, list(aliases))


@router.delete("/faqs/{faq_id}", status_code=204)
async def delete_faq(
    faq_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    entry = await session.scalar(
        select(FaqEntry).where(
            FaqEntry.id == faq_id,
            FaqEntry.business_id == principal.business_id,
        )
    )
    if entry is None:
        raise NotFound("No such FAQ.")
    await session.delete(entry)
    await session.commit()


@router.post("/sessions")
async def create_chat_session(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, uuid.UUID]:
    now = datetime.now(UTC)
    chat = ChatSession(
        business_id=principal.business_id,
        user_id=principal.user_id,
        started_at=now,
        last_message_at=now,
    )
    session.add(chat)
    await session.commit()
    return {"id": chat.id}


@router.post("/sessions/{session_id}/messages", response_model=ChatOut)
async def send_chat_message(
    session_id: uuid.UUID,
    body: ChatIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> ChatOut:
    chat = await session.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.business_id == principal.business_id,
            ChatSession.user_id == principal.user_id,
        )
    )
    if chat is None:
        raise NotFound("No such chat session.")
    if body.image_attached:
        raise BadRequest("Image analysis is not supported yet.")
    started = time.monotonic()
    question = body.content
    faq = await match_faq(session, business_id=principal.business_id, question=question)
    route = AnswerType.faq.value if faq else AnswerType.ai.value
    references: dict[str, Any] = {}
    tools: list[str] = []
    if faq is not None:
        answer = faq.answer
        answer_type = AnswerType.faq.value
        input_tokens = output_tokens = 0
    elif blocked_intent(question):
        answer = "I can only answer questions and cannot make changes or send messages."
        answer_type = AnswerType.blocked.value
        input_tokens = output_tokens = 0
    elif "how many active ads" in question.lower():
        result = await run_read_tool(
            session, business_id=principal.business_id, name="active_ads_count"
        )
        answer = f"Verified active ads: {result['value']}."
        answer_type = AnswerType.data.value
        references = result
        tools = ["active_ads_count"]
        input_tokens = output_tokens = 0
        route = AnswerType.data.value
    else:
        answer, input_tokens, output_tokens = await StubLLM().answer(
            f"<untrusted-user-question>{question}</untrusted-user-question>"
        )
        answer_type = AnswerType.ai.value
    now = datetime.now(UTC)
    session.add_all(
        [
            ChatMessage(
                business_id=principal.business_id,
                chat_session_id=chat.id,
                role=ChatRole.user.value,
                content=body.content,
            ),
            ChatMessage(
                business_id=principal.business_id,
                chat_session_id=chat.id,
                role=ChatRole.assistant.value,
                content=answer,
                answer_type=answer_type,
                references=references,
                data_as_of=now,
            ),
            AiUsageEvent(
                business_id=principal.business_id,
                user_id=principal.user_id,
                chat_session_id=chat.id,
                route=route,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=Decimal("0"),
                latency_ms=int((time.monotonic() - started) * 1000),
                tools_invoked=tools,
                prompt_hash=hashlib.sha256(question.encode()).hexdigest(),
                created_at=now,
            ),
        ]
    )
    chat.last_message_at = now
    await session.commit()
    return ChatOut(
        answer=answer,
        answer_type=answer_type,
        references=references,
        data_as_of=now,
        usage={"route": route, "input_tokens": input_tokens, "output_tokens": output_tokens},
    )


@router.post("/tours/steps", response_model=TourStepOut)
async def create_tour_step(
    body: TourIn,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> TourStepOut:
    step = TourStep(business_id=principal.business_id, **body.model_dump())
    session.add(step)
    await session.commit()
    return TourStepOut.model_validate(step, from_attributes=True)


@router.get("/tours/steps")
async def list_tour_steps(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[TourStepOut]:
    steps = list(
        (
            await session.execute(
                select(TourStep)
                .where(
                    TourStep.business_id == principal.business_id,
                    TourStep.is_active.is_(True),
                )
                .order_by(TourStep.step_order)
            )
        ).scalars()
    )
    return [TourStepOut.model_validate(step, from_attributes=True) for step in steps]


@router.post("/tours/steps/reorder")
async def reorder_tour_steps(
    step_ids: list[uuid.UUID],
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any]:
    steps = list(
        (
            await session.execute(
                select(TourStep).where(
                    TourStep.business_id == principal.business_id,
                    TourStep.id.in_(step_ids),
                )
            )
        ).scalars()
    )
    if len(steps) != len(step_ids):
        raise NotFound("One or more tour steps do not exist.")
    by_id = {step.id: step for step in steps}
    for order, step_id in enumerate(step_ids, start=1):
        by_id[step_id].step_order = order
    await session.commit()
    return {"step_ids": step_ids}


@router.post("/tours/progress")
async def update_tour_progress(
    state: TourState,
    current_step: int = 1,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any]:
    progress = await session.scalar(
        select(TourProgress).where(
            TourProgress.business_id == principal.business_id,
            TourProgress.user_id == principal.user_id,
            TourProgress.tour_key == "agent-workspace",
        )
    )
    if progress is None:
        progress = TourProgress(
            business_id=principal.business_id,
            user_id=principal.user_id,
            tour_key="agent-workspace",
        )
        session.add(progress)
    progress.state = state.value
    progress.current_step = current_step
    progress.completed_at = datetime.now(UTC) if state == TourState.completed else None
    await session.commit()
    return {"state": progress.state, "current_step": progress.current_step}


@router.post("/tours/steps/{step_id}/activate")
async def activate_tour_step(
    step_id: uuid.UUID,
    target_found: bool = True,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any]:
    step = await session.scalar(
        select(TourStep).where(
            TourStep.id == step_id,
            TourStep.business_id == principal.business_id,
        )
    )
    if step is None:
        raise NotFound("No such tour step.")
    step.is_active = target_found
    await session.commit()
    return {"id": step.id, "active": step.is_active, "skipped": not target_found}
