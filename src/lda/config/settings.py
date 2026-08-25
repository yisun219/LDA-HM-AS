from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    e2b_api_url: str = "https://e2b.fact-lab.work"
    e2b_sandbox_url: str = "https://e2b.fact-lab.work"
    e2b_access_token: str = "dummy"
    e2b_api_key_env: str = "E2B_API_KEY"
    max_life_cycles: int = 20

    @classmethod
    def from_env(cls) -> "Settings":
        api = os.environ.get("E2B_API_URL", cls.e2b_api_url)
        return cls(api, os.environ.get("E2B_SANDBOX_URL", api), os.environ.get("E2B_ACCESS_TOKEN", cls.e2b_access_token),
                   os.environ.get("E2B_API_KEY_ENV", cls.e2b_api_key_env), int(os.environ.get("LDA_MAX_LIFE_CYCLES", "20")))

