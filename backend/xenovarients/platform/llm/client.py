"""Small Ollama client with bounded concurrency and explicit failures."""

import asyncio
from typing import Any

import httpx

from xenovarients.core.config import get_settings


class LlmUnavailable(RuntimeError):
    """Raised when Ollama cannot satisfy a request."""


class OllamaClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._chat_model = settings.llm_chat_model
        self._embedding_model = settings.embedding_model
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

    async def embed(self, text: str) -> list[float]:
        async with self._semaphore:
            embedding = await self._post_embedding(text)
        expected = get_settings().embedding_dim
        if len(embedding) != expected:
            raise LlmUnavailable(
                f"Embedding dimension mismatch: expected {expected}, got {len(embedding)}."
            )
        return embedding

    async def chat(self, messages: list[dict[str, str]]) -> str:
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(
                        f"{self._base_url}/api/chat",
                        json={"model": self._chat_model, "messages": messages, "stream": False},
                    )
                response.raise_for_status()
            except (httpx.HTTPError, ValueError) as exc:
                raise LlmUnavailable("Ollama chat is unavailable.") from exc
            payload: Any = response.json()
            content = payload.get("message", {}).get("content")
            if not isinstance(content, str):
                raise LlmUnavailable("Ollama returned an invalid chat response.")
            return content

    async def _post_embedding(self, text: str) -> list[float]:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._embedding_model, "input": text},
                )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            raise LlmUnavailable("Ollama embeddings are unavailable.") from exc
        payload: Any = response.json()
        embeddings = payload.get("embeddings")
        if (
            not isinstance(embeddings, list)
            or not embeddings
            or not isinstance(embeddings[0], list)
        ):
            raise LlmUnavailable("Ollama returned an invalid embedding response.")
        return [float(value) for value in embeddings[0]]
