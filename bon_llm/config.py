from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BON_", extra="ignore")

    config_path: str = "config/config.yaml"


class ProviderConfig(BaseModel):
    base_url: str
    base_url_env: str | None = None
    api_key_env: str | None = None
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=2, ge=0)

    def resolved_api_key(self) -> str | None:
        if self.api_key is not None:
            return self.api_key.get_secret_value()
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None

    def resolved_base_url(self) -> str:
        return (os.getenv(self.base_url_env) if self.base_url_env else None) or self.base_url


class SamplingConfig(BaseModel):
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        updated = dict(payload)
        if self.temperature is not None:
            updated["temperature"] = self.temperature
        if self.top_p is not None:
            updated["top_p"] = self.top_p
        if self.max_tokens is not None:
            updated["max_tokens"] = self.max_tokens
        return updated


class CandidateConfig(BaseModel):
    provider: str
    model: str
    count: int | None = Field(default=None, ge=1)
    weight: float | None = Field(default=None, gt=0)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)


class JudgeConfig(BaseModel):
    provider: str
    model: str
    sampling: SamplingConfig = Field(default_factory=lambda: SamplingConfig(temperature=0))
    prompt: str | None = None


class StrategyConfig(BaseModel):
    n: int = Field(default=3, ge=1)
    judge: JudgeConfig
    candidates: list[CandidateConfig] = Field(min_length=1)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)


class AppConfig(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    strategies: dict[str, StrategyConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "AppConfig":
        for strategy_name, strategy in self.strategies.items():
            fixed_count = sum(candidate.count or 0 for candidate in strategy.candidates)
            if fixed_count > strategy.n:
                raise ValueError(f"strategy {strategy_name}: candidate fixed counts exceed n")
            if fixed_count < strategy.n and all(candidate.count is not None for candidate in strategy.candidates):
                raise ValueError(f"strategy {strategy_name}: candidate counts do not fill n")
            for candidate in strategy.candidates:
                if candidate.provider not in self.providers:
                    raise ValueError(f"strategy {strategy_name} references unknown provider {candidate.provider}")
            if strategy.judge.provider not in self.providers:
                raise ValueError(f"strategy {strategy_name} judge references unknown provider {strategy.judge.provider}")
        return self


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or RuntimeSettings().config_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return AppConfig.model_validate(data)
