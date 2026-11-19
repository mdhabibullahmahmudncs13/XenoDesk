"""MongoDB access kept behind one tenant-enforcing repository."""

from datetime import datetime
from typing import Any
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorClient

from xenovarients.core.config import get_settings


class DocumentRepository:
    def __init__(self, client: AsyncIOMotorClient | None = None) -> None:
        settings = get_settings()
        self._client = client or AsyncIOMotorClient(
            settings.mongo_uri, serverSelectionTimeoutMS=1000
        )
        self._collection = self._client[settings.mongo_db_name]["agent_traces"]

    async def append_trace(self, *, business_id: UUID, payload: dict[str, Any]) -> None:
        await self._collection.insert_one(
            {
                "business_id": str(business_id),
                "payload": payload,
                "created_at": datetime.utcnow(),
            }
        )

    async def close(self) -> None:
        self._client.close()
