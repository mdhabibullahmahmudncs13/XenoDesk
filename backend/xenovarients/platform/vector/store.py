"""Vector-store boundary used by retrieval code."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.embedding import EmbeddingChunk


@dataclass(frozen=True)
class VectorHit:
    chunk_id: UUID
    score: float
    content: str


class VectorStore(Protocol):
    async def search(
        self, session: AsyncSession, *, business_id: UUID, embedding: list[float], limit: int
    ) -> list[VectorHit]: ...


class PgVectorStore:
    """Default vector implementation; the session's RLS enforces tenant isolation."""

    async def search(
        self, session: AsyncSession, *, business_id: UUID, embedding: list[float], limit: int
    ) -> list[VectorHit]:
        distance = EmbeddingChunk.embedding.cosine_distance(embedding)
        rows = await session.execute(
            select(EmbeddingChunk, distance.label("distance"))
            .where(EmbeddingChunk.business_id == business_id)
            .order_by(distance)
            .limit(limit)
        )
        return [
            VectorHit(chunk_id=chunk.id, score=1.0 - float(distance_value), content=chunk.content)
            for chunk, distance_value in rows.all()
        ]
