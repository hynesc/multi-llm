from __future__ import annotations

import asyncio
import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from bon_llm.config import AppConfig, CandidateConfig, JudgeConfig, StrategyConfig
from bon_llm.provider import ProviderRegistry
from bon_llm.schemas import ChatChoice, ChatCompletionRequest, ChatCompletionResponse, ModelCard, ModelListResponse


@dataclass(frozen=True)
class CandidateSpec:
    index: int
    provider: str
    model: str
    payload: dict[str, Any]


@dataclass
class CandidateResult:
    index: int
    provider: str
    model: str
    payload: dict[str, Any]
    response: dict[str, Any] | None
    error: str | None
    latency_seconds: float

    @property
    def content(self) -> str:
        if not self.response:
            return ""
        choices = self.response.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        return content if isinstance(content, str) else ""


@dataclass
class Selection:
    winner: CandidateResult
    source: str
    reason: str | None = None


class BestOfNEngine:
    def __init__(self, config: AppConfig, providers: ProviderRegistry):
        self.config = config
        self.providers = providers

    async def list_models(self) -> ModelListResponse:
        return ModelListResponse(data=[ModelCard(id=name) for name in sorted(self.config.strategies)])

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        result = await self.run_strategy(request.model, request)
        if result["winner"].response is None or not result["winner"].content.strip():
            raise HTTPException(status_code=502, detail="all candidate generations failed")
        winner = result["winner"]
        return build_response(request.model, winner.response or {}, winner.content)

    async def run_strategy(self, strategy_name: str, request: ChatCompletionRequest) -> dict[str, Any]:
        strategy = self.config.strategies.get(strategy_name)
        if strategy is None:
            raise HTTPException(status_code=404, detail=f"unknown strategy: {strategy_name}")
        specs = expand_candidates(request, strategy)
        candidates = await self._generate(specs)
        selection = await self._select(request, strategy.judge, candidates)
        return {
            "strategy": strategy_name,
            "winner": selection.winner,
            "selection_source": selection.source,
            "selection_reason": selection.reason,
            "candidates": candidates,
        }

    async def _generate(self, specs: list[CandidateSpec]) -> list[CandidateResult]:
        return await asyncio.gather(*(self._run_candidate(spec) for spec in specs))

    async def _run_candidate(self, spec: CandidateSpec) -> CandidateResult:
        started = time.perf_counter()
        try:
            response = await self.providers.get(spec.provider).chat_completion(spec.payload)
            return CandidateResult(
                index=spec.index,
                provider=spec.provider,
                model=spec.model,
                payload=spec.payload,
                response=response,
                error=None,
                latency_seconds=time.perf_counter() - started,
            )
        except Exception as exc:
            return CandidateResult(
                index=spec.index,
                provider=spec.provider,
                model=spec.model,
                payload=spec.payload,
                response=None,
                error=str(exc),
                latency_seconds=time.perf_counter() - started,
            )

    async def _select(
        self, request: ChatCompletionRequest, judge: JudgeConfig, candidates: list[CandidateResult]
    ) -> Selection:
        valid = [candidate for candidate in candidates if candidate.content.strip()]
        if len(valid) == 1:
            return Selection(valid[0], "single_valid", "only one candidate completed")
        if not valid:
            return Selection(heuristic_select(candidates), "fallback", "no valid candidates")

        judge_payload = {
            "model": judge.model,
            "stream": False,
            "temperature": judge.sampling.temperature or 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict response judge. Return JSON only with keys "
                        "winner_index and reason. winner_index must match a candidate index."
                    ),
                },
                {"role": "user", "content": build_judge_prompt(request.messages, valid, judge.prompt)},
            ],
        }
        judge_payload = judge.sampling.apply(judge_payload)
        try:
            judge_response = await self.providers.get(judge.provider).chat_completion(judge_payload)
            content = extract_content(judge_response)
            parsed = parse_json_object(content)
            winner_index = parsed.get("winner_index") if parsed else None
            if isinstance(winner_index, int):
                winner = next((candidate for candidate in valid if candidate.index == winner_index), None)
                if winner:
                    return Selection(winner, "judge", parsed.get("reason"))
        except Exception:
            pass
        return Selection(heuristic_select(candidates), "fallback", "judge failed or returned invalid selection")


def request_to_payload(request: ChatCompletionRequest) -> dict[str, Any]:
    # Normalize the client's max_completion_tokens alias to max_tokens so
    # strategy/candidate sampling overrides replace it rather than adding a
    # conflicting second token-limit field to the provider request.
    payload = request.model_dump(exclude_none=True)
    payload["messages"] = [message.model_dump(exclude_none=True) for message in request.messages]
    payload["stream"] = False
    return payload


def expand_candidates(request: ChatCompletionRequest, strategy: StrategyConfig) -> list[CandidateSpec]:
    base_payload = request_to_payload(request)
    base_payload = strategy.sampling.apply(base_payload)
    candidates = expand_candidate_configs(strategy.candidates, strategy.n)
    specs: list[CandidateSpec] = []
    for idx, candidate in enumerate(candidates):
        payload = dict(base_payload)
        payload["model"] = candidate.model
        payload = candidate.sampling.apply(payload)
        payload["seed"] = seed_for_index(request.seed, idx)
        specs.append(CandidateSpec(idx, candidate.provider, candidate.model, payload))
    return specs


def expand_candidate_configs(candidates: list[CandidateConfig], total_n: int) -> list[CandidateConfig]:
    fixed = [candidate for candidate in candidates if candidate.count is not None]
    weighted = [candidate for candidate in candidates if candidate.count is None]
    expanded: list[CandidateConfig] = []
    fixed_count = sum(candidate.count or 0 for candidate in fixed)
    if fixed_count > total_n:
        raise ValueError("candidate fixed counts exceed strategy n")
    for candidate in fixed:
        expanded.extend([candidate] * (candidate.count or 0))
    remaining = total_n - fixed_count
    if remaining == 0:
        return expanded
    if not weighted:
        raise ValueError("not enough weighted candidates to satisfy strategy n")
    total_weight = sum(candidate.weight or 1.0 for candidate in weighted)
    assigned = 0
    remainders: list[tuple[float, CandidateConfig]] = []
    for candidate in weighted:
        exact = remaining * ((candidate.weight or 1.0) / total_weight)
        count = int(exact)
        expanded.extend([candidate] * count)
        assigned += count
        remainders.append((exact - count, candidate))
    for _, candidate in sorted(remainders, key=lambda item: item[0], reverse=True)[: remaining - assigned]:
        expanded.append(candidate)
    return expanded


def seed_for_index(seed: int | None, index: int) -> int:
    if seed is not None:
        return seed + index
    return random.randint(0, 2**31 - 1)


def build_judge_prompt(messages: list[Any], candidates: list[CandidateResult], custom: str | None) -> str:
    rubric = custom or (
        "Choose the best assistant reply. Favor correctness, supported claims, relevance, "
        "and instruction-following. Prefer clear, specific answers when the available information "
        "supports them. Acknowledge uncertainty or missing information and ask for clarification "
        "when needed. Do not penalize an answer merely for expressing uncertainty, declining to "
        "speculate, or appropriately refusing a request. Penalize unsupported claims, fabricated "
        "details, empty answers, and unnecessary refusals when a supported answer is available."
    )
    conversation = json.dumps([message.model_dump() for message in messages], ensure_ascii=True)
    candidate_blocks = [
        f"Candidate {candidate.index} ({candidate.provider}/{candidate.model}):\n{candidate.content}"
        for candidate in candidates
    ]
    return f"{rubric}\n\nConversation:\n{conversation}\n\nCandidates:\n" + "\n\n".join(candidate_blocks)


def parse_json_object(content: Any) -> dict[str, Any]:
    if not isinstance(content, str):
        return {}
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""


def heuristic_select(candidates: list[CandidateResult]) -> CandidateResult:
    return sorted(candidates, key=_heuristic_score, reverse=True)[0]


def _heuristic_score(candidate: CandidateResult) -> tuple[int, int, int]:
    content = candidate.content.strip()
    completed = 1 if candidate.response is not None else 0
    non_empty = 1 if content else 0
    return (completed + non_empty, non_empty, min(len(content), 4000))


def build_response(model_name: str, upstream_response: dict[str, Any], content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=model_name,
        choices=[ChatChoice(message={"role": "assistant", "content": content})],
        usage=upstream_response.get("usage"),
    )
