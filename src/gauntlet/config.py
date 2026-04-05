"""
config.py — Runtime configuration.

Two model roles:
  primary  — all five reasoning agents (high capability required)
  fast     — translation layer + contrary generation (cheap + quick)

Per-agent overrides are available for fine-grained control.
Any OpenRouter model string works for either role.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    model:              str
    max_tokens:         int = 4096
    retries:            int = 2
    max_tool_iters:     int = 10


@dataclass(frozen=True)
class GauntletConfig:
    # Model roles
    primary:  AgentConfig
    fast:     AgentConfig

    # Infrastructure
    openrouter_api_key:  str
    openrouter_base_url: str
    tavily_api_key:      str

    # Per-agent overrides (None = use primary)
    constructor_cfg: AgentConfig | None = None
    classifier_cfg:  AgentConfig | None = None
    auditor_cfg:     AgentConfig | None = None
    evaluator_cfg:   AgentConfig | None = None
    resolver_cfg:    AgentConfig | None = None

    # Resolved accessors — no __post_init__ mutation required
    @property
    def for_constructor(self) -> AgentConfig:
        return self.constructor_cfg or self.primary

    @property
    def for_classifier(self) -> AgentConfig:
        return self.classifier_cfg or self.primary

    @property
    def for_auditor(self) -> AgentConfig:
        return self.auditor_cfg or self.primary

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
        return cls(
            primary=AgentConfig(
                model=os.environ.get("GAUNTLET_PRIMARY_MODEL", "anthropic/claude-opus-4-6"),
            ),
            fast=AgentConfig(
                model=os.environ.get("GAUNTLET_FAST_MODEL", "anthropic/claude-haiku-4-5"),
                max_tokens=512,
            ),
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            openrouter_base_url=os.environ.get(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
            tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
        )
