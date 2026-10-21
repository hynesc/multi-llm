from __future__ import annotations

import httpx

from bon_llm.config import ProviderConfig
from bon_llm.provider import OpenAICompatibleProvider


async def test_provider_preserves_v1_base_path() -> None:
    seen_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = httpx.AsyncClient(
        base_url="http://example.test/v1/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICompatibleProvider("test", ProviderConfig(base_url="http://example.test/v1"), client)

    await provider.chat_completion({"model": "m", "messages": []})
    await client.aclose()

    assert seen_urls == ["http://example.test/v1/chat/completions"]
