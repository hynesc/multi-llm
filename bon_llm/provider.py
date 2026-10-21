from __future__ import annotations

import asyncio
from typing import Any

import httpx

from bon_llm.config import ProviderConfig


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, name: str, config: ProviderConfig, client: httpx.AsyncClient | None = None):
        self.name = name
        self.config = config
        self._client = client

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "chat/completions", json=payload)

    async def list_models(self) -> list[str]:
        response = await self._request("GET", "models")
        models = response.get("data") or []
        return [item["id"] for item in models if isinstance(item, dict) and isinstance(item.get("id"), str)]

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        close_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(base_url=f"{self.config.resolved_base_url().rstrip('/')}/", timeout=self.config.timeout_seconds)
            close_client = True
        try:
            headers = kwargs.pop("headers", {})
            api_key = self.config.resolved_api_key()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            last_error: Exception | None = None
            for attempt in range(self.config.max_retries + 1):
                try:
                    response = await client.request(method, path, headers=headers, **kwargs)
                    response.raise_for_status()
                    return response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    if attempt < self.config.max_retries:
                        await asyncio.sleep(0.25 * (2**attempt))
            raise ProviderError(f"{self.name} request failed: {last_error}") from last_error
        finally:
            if close_client:
                await client.aclose()


class ProviderRegistry:
    def __init__(self, providers: dict[str, ProviderConfig]):
        self._providers = {
            name: OpenAICompatibleProvider(name, config) for name, config in providers.items()
        }

    def get(self, name: str) -> OpenAICompatibleProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderError(f"unknown provider: {name}") from exc
