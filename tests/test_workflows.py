import json

import httpx
import pytest

from bon_llm.api import create_app
from bon_llm.config import AppConfig
from bon_llm.engine import BestOfNEngine


class FakeProvider:
    def __init__(self, judge_content='{"winner_index": 1, "reason": "correct"}', failed=None):
        self.judge_content = judge_content
        self.failed = failed or set()
        self.models_called = []

    async def chat_completion(self, payload):
        model = payload["model"]
        self.models_called.append(model)
        if model in self.failed:
            raise RuntimeError("simulated upstream failure")
        content = {"candidate-a": "A brief answer", "candidate-b": "42", "judge": self.judge_content}[model]
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}

    def get(self, name):
        return self


def workflow_config(tmp_path):
    return AppConfig.model_validate({
        "providers": {"fake": {"base_url": "http://example.test/v1"}},
        "strategies": {"bon/test": {
            "n": 2,
            "candidates": [
                {"provider": "fake", "model": "candidate-a", "count": 1},
                {"provider": "fake", "model": "candidate-b", "count": 1},
            ],
            "judge": {"provider": "fake", "model": "judge"},
        }},
    })


async def test_chat_returns_judged_winner_and_sse(tmp_path):
    provider = FakeProvider()
    app = create_app(workflow_config(tmp_path), provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        models = (await client.get("/v1/models")).json()
        assert [model["id"] for model in models["data"]] == ["bon/test"]
        payload = {"model": "bon/test", "messages": [{"role": "user", "content": "17 + 25?"}]}
        response = await client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "42"
        streamed = await client.post("/v1/chat/completions", json={**payload, "stream": True})
        assert streamed.headers["content-type"].startswith("text/event-stream")
        events = [line[6:] for line in streamed.text.splitlines() if line.startswith("data: ")]
        assert json.loads(events[0])["choices"][0]["delta"]["content"] == "42"
        assert events[-1] == "[DONE]"
        missing = await client.post("/v1/chat/completions", json={**payload, "model": "missing"})
        assert missing.status_code == 404


@pytest.mark.parametrize("judge_content", ["not json", '{"winner_index": 99}'])
async def test_invalid_judge_uses_fallback(tmp_path, judge_content):
    from bon_llm.schemas import ChatCompletionRequest
    engine = BestOfNEngine(workflow_config(tmp_path), FakeProvider(judge_content))
    result = await engine.run_strategy("bon/test", ChatCompletionRequest(model="bon/test", messages=[{"role": "user", "content": "hello"}]))
    assert result["selection_source"] == "fallback"
    assert result["winner"].content


async def test_partial_failure_returns_remaining_candidate_without_judge(tmp_path):
    provider = FakeProvider(failed={"candidate-a"})
    app = create_app(workflow_config(tmp_path), provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json={"model": "bon/test", "messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "42"
    assert "judge" not in provider.models_called


@pytest.mark.parametrize("failed", [{"candidate-a", "candidate-b"}, set()])
async def test_no_usable_candidates_returns_bad_gateway(tmp_path, failed):
    provider = FakeProvider(failed=failed)
    original = provider.chat_completion

    async def empty_or_failed(payload):
        response = await original(payload)
        response["choices"][0]["message"]["content"] = "  "
        return response

    provider.chat_completion = empty_or_failed
    app = create_app(workflow_config(tmp_path), provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json={"model": "bon/test", "messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 502
