from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from bon_llm.config import AppConfig, load_config
from bon_llm.engine import BestOfNEngine
from bon_llm.provider import ProviderRegistry
from bon_llm.schemas import ChatCompletionRequest, ChatCompletionResponse, ModelListResponse


def create_app(config: AppConfig | None = None, providers: ProviderRegistry | None = None) -> FastAPI:
    config = config if config is not None else load_config()
    engine = BestOfNEngine(config, providers if providers is not None else ProviderRegistry(config.providers))
    app = FastAPI(title="Multi-LLM", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models", response_model=ModelListResponse)
    async def list_models() -> ModelListResponse:
        return await engine.list_models()

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse | StreamingResponse:
        response = await engine.chat(request)
        if request.stream:
            async def events():
                chunk = {
                    "id": response.id,
                    "object": "chat.completion.chunk",
                    "created": response.created,
                    "model": response.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": response.choices[0].message.content},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")
        return response

    return app


app = create_app()
