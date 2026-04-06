"""
config.py - Runtime configuration.

Two model roles:
  primary   - reasoning stages
  preflight - parsing and contrary generation

Per-stage overrides are available where the runtime still needs separate
execution contexts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    model: str
    max_tokens: int = 4096
    retries: int = 2
    max_tool_iters: int = 10


@dataclass(frozen=True)
class GauntletConfig:
    primary: AgentConfig
    preflight: AgentConfig

    openrouter_api_key: str
    openrouter_base_url: str
    tavily_api_key: str = ""

    constructor_cfg: AgentConfig | None = None
    critique_cfg: AgentConfig | None = None
    evaluator_cfg: AgentConfig | None = None
    resolver_cfg: AgentConfig | None = None

    @property
    def for_constructor(self) -> AgentConfig:
        return self.constructor_cfg or self.primary

    @property
    def for_critique(self) -> AgentConfig:
        return self.critique_cfg or self.primary

    @property
    def for_evaluator(self) -> AgentConfig:
        return self.evaluator_cfg or self.primary

    @property
    def for_resolver(self) -> AgentConfig:
        return self.resolver_cfg or self.primary

    @classmethod
    def from_env(cls) -> "GauntletConfig":
        from dotenv import load_dotenv

        load_dotenv()
        preflight_model = (
            os.environ.get("GAUNTLET_PREFLIGHT_MODEL")
            or os.environ.get("GAUNTLET_FAST_MODEL")
            or "anthropic/claude-haiku-4-5"
        )
        return cls(
            primary=AgentConfig(
                model=os.environ.get("GAUNTLET_PRIMARY_MODEL", "anthropic/claude-opus-4-6"),
            ),
            preflight=AgentConfig(
                model=preflight_model,
                max_tokens=512,
            ),
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            openrouter_base_url=os.environ.get(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
            tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
        )
