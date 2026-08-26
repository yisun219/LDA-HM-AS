from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType

from e2b import Template

from lda.config import LDAConfig

from .shared_gateway import configure_shared_gateway
from .template_compat import configure_template_build_compatibility


CODEX_CLI_VERSION = "0.149.1"
INTEL_SKILLS_COMMIT = "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c"


def _builders(root: Path) -> ModuleType:
    path = root / "e2b_builders.py"
    specification = importlib.util.spec_from_file_location("lda_e2b_builders", path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load E2B builders from {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def build_templates(config: LDAConfig, root: Path, *, all_templates: bool = True, rebuild: bool = False) -> list[str]:
    config.e2b.apply_public_environment()
    config.e2b.api_key()
    configure_shared_gateway()
    configure_template_build_compatibility()
    if importlib.metadata.version("e2b") != config.e2b.sdk_version:
        raise RuntimeError("refusing to build templates with a different E2B SDK")
    builders = _builders(root)
    definitions = [
        (config.e2b.controller_template, builders.controller_template),
        (config.e2b.agent_template, builders.agent_template),
        (config.e2b.base_template, builders.base_template),
        (config.e2b.judge_template, lambda: builders.judge_template(config.e2b.base_template)),
        (config.e2b.e2e_template, builders.e2e_template),
    ]
    built: list[str] = []
    for alias, factory in definitions:
        exists = False
        for attempt in range(8):
            try:
                exists = bool(Template.exists(alias))
                break
            except Exception as error:
                message = str(error).lower()
                transient = any(marker in message for marker in ("530", "502", "503", "timeout", "connection"))
                if not transient or attempt == 7:
                    raise
                time.sleep(min(2 ** attempt, 10))
        if exists and not rebuild:
            print(f"[lda template] exists {alias}", file=sys.stderr, flush=True)
            continue
        print(f"[lda template] building {alias}", file=sys.stderr, flush=True)

        def log(entry, *, template_alias=alias) -> None:
            print(f"[{template_alias}] {entry.level}: {entry.message}", file=sys.stderr, flush=True)

        Template.build(
            factory(),
            alias,
            cpu_count=8 if alias in {config.e2b.base_template, config.e2b.judge_template, config.e2b.e2e_template} else 2,
            memory_mb=16384 if alias in {config.e2b.base_template, config.e2b.judge_template, config.e2b.e2e_template} else 4096,
            skip_cache=rebuild,
            on_build_logs=log,
        )
        print(f"[lda template] ready {alias}", file=sys.stderr, flush=True)
        built.append(alias)
    return built
