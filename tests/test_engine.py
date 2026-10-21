from __future__ import annotations

from bon_llm.config import CandidateConfig, JudgeConfig, SamplingConfig, StrategyConfig
from bon_llm.engine import (
    CandidateResult,
    expand_candidate_configs,
    expand_candidates,
    heuristic_select,
    parse_json_object,
)
from bon_llm.schemas import ChatCompletionRequest


def test_expand_single_weighted_candidate_to_n() -> None:
    strategy = StrategyConfig(
        n=3,
        candidates=[CandidateConfig(provider="local", model="model-a")],
        judge=JudgeConfig(provider="local", model="judge-a"),
    )
    request = ChatCompletionRequest(
        model="bon/test",
        seed=10,
        messages=[{"role": "user", "content": "hello"}],
    )

    specs = expand_candidates(request, strategy)

    assert [spec.model for spec in specs] == ["model-a", "model-a", "model-a"]
    assert [spec.payload["seed"] for spec in specs] == [10, 11, 12]
    assert all(spec.payload["stream"] is False for spec in specs)


def test_expand_pool_honors_counts_and_weights() -> None:
    candidates = expand_candidate_configs(
        [
            CandidateConfig(provider="local", model="fixed", count=1),
            CandidateConfig(provider="local", model="heavy", weight=3),
            CandidateConfig(provider="local", model="light", weight=1),
        ],
        total_n=5,
    )

    assert [candidate.model for candidate in candidates].count("fixed") == 1
    assert [candidate.model for candidate in candidates].count("heavy") == 3
    assert [candidate.model for candidate in candidates].count("light") == 1


def test_candidate_sampling_overrides_openai_request_limits_without_duplicate_aliases() -> None:
    strategy = StrategyConfig(
        n=1,
        candidates=[CandidateConfig(
            provider="local", model="model-a",
            sampling=SamplingConfig(max_tokens=128, temperature=0.9),
        )],
        judge=JudgeConfig(provider="local", model="judge-a"),
        sampling=SamplingConfig(max_tokens=512, temperature=0.5),
    )
    request = ChatCompletionRequest(
        model="bon/test",
        max_completion_tokens=1024,
        temperature=0.1,
        messages=[{"role": "user", "content": "hello"}],
    )

    payload = expand_candidates(request, strategy)[0].payload

    assert payload["max_tokens"] == 128
    assert payload["temperature"] == 0.9
    assert "max_completion_tokens" not in payload


def test_parse_json_object_extracts_object_from_text() -> None:
    assert parse_json_object('winner: {"winner_index": 2, "reason": "best"}') == {
        "winner_index": 2,
        "reason": "best",
    }


def test_heuristic_prefers_non_empty_completed_answer() -> None:
    empty = CandidateResult(0, "local", "a", {}, {"choices": [{"message": {"content": ""}}]}, None, 0.1)
    good = CandidateResult(1, "local", "b", {}, {"choices": [{"message": {"content": "Useful answer"}}]}, None, 0.1)
    failed = CandidateResult(2, "local", "c", {}, None, "failed", 0.1)

    assert heuristic_select([empty, good, failed]).index == 1
