from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class E2BConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sdk_version: str = "2.45.0"
    api_url: str = "https://e2b.fact-lab.work"
    sandbox_url: str = "https://e2b.fact-lab.work"
    access_token: str = "dummy"
    api_key_env: str = "E2B_API_KEY"
    shared_gateway: bool = True
    validate_api_key: bool = True
    controller_template: str = "lda-controller-lda-hm-0-3-29"
    agent_template: str = "lda-agent-runtime-lda-hm-0-3-9"
    base_template: str = "lda-base-lda-hm-0-3-3"
    judge_template: str = "lda-judge-lda-hm-0-3-6"
    e2e_template: str = "lda-e2e-lda-hm-0-3-2"

    def apply_public_environment(self) -> None:
        os.environ.setdefault("E2B_API_URL", self.api_url)
        os.environ.setdefault("E2B_SANDBOX_URL", self.sandbox_url)
        os.environ.setdefault("E2B_ACCESS_TOKEN", self.access_token)

    def api_key(self) -> str:
        value = os.getenv(self.api_key_env, "")
        if self.validate_api_key and not value.startswith("e2b_"):
            raise RuntimeError(f"{self.api_key_env} is missing or invalid")
        return value


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_active_missions: int = Field(default=2, ge=1)
    builders_per_mission: int = Field(default=3, ge=1)
    max_live_codex_sessions: int = Field(default=8, ge=1)
    max_live_sandboxes: int = Field(default=20, ge=1)
    max_candidates_per_mission: int = Field(default=3, ge=1)
    max_attempts_per_candidate: int = Field(default=8, ge=1)


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    warmups: int = Field(default=10, ge=10)
    samples: int = Field(default=30, ge=30)
    min_micro_speedup: float = 1.03
    min_micro_ci_lower: float = 1.01
    max_e2e_regression: float = 0.005
    portfolio_min_geomean_speedup: float = 1.01
    min_improved_e2e_workloads: int = 2
    max_noise_cv: float = 0.05


class LDAConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    e2b: E2BConfig = Field(default_factory=E2BConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    state_root: Path = Path(".lda/state")
    artifact_root: Path = Path(".lda/artifacts")
    capability_signing_key_env: str = "LDA_CAPABILITY_SIGNING_KEY"
    ubuntu_snapshot: str = "https://snapshot.ubuntu.com/ubuntu/20260825T000000Z"

    @model_validator(mode="after")
    def validate_limits(self) -> "LDAConfig":
        required = self.scheduler.max_active_missions * self.scheduler.builders_per_mission
        if required > self.scheduler.max_live_codex_sessions:
            raise ValueError("scheduler can create more builders than live Codex sessions")
        return self

    @classmethod
    def load(cls, path: Path | None = None) -> "LDAConfig":
        if path is None:
            path = Path(os.getenv("LDA_CONFIG", "configs/lda.yaml"))
        if not path.exists():
            return cls()
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
