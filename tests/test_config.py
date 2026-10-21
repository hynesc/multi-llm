from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bon_llm.config import AppConfig, ProviderConfig, load_config


def test_load_config_validates_references(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
providers:
  local:
    base_url: http://localhost:11434/v1
strategies:
  bon/test:
    n: 2
    candidates:
      - provider: local
        model: model-a
    judge:
      provider: local
      model: judge-a
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.strategies["bon/test"].n == 2


def test_provider_endpoint_can_be_overridden_without_private_config(monkeypatch):
    provider = ProviderConfig(base_url="http://localhost:11434/v1", base_url_env="TEST_PROVIDER_URL")
    monkeypatch.setenv("TEST_PROVIDER_URL", "http://example.test:11434/v1")
    assert provider.resolved_base_url() == "http://example.test:11434/v1"
    monkeypatch.delenv("TEST_PROVIDER_URL")
    assert provider.resolved_base_url() == "http://localhost:11434/v1"


@pytest.mark.parametrize("n,count", [(1, 2), (3, 1)])
def test_invalid_candidate_allocations_fail_at_configuration_time(n, count):
    with pytest.raises(ValidationError, match="candidate"):
        AppConfig.model_validate({
            "providers": {"local": {"base_url": "http://example.test/v1"}},
            "strategies": {"bon/test": {"n": n, "candidates": [{"provider": "local", "model": "test", "count": count}], "judge": {"provider": "local", "model": "test"}}},
        })
