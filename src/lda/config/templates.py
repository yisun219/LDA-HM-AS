from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping


TEMPLATE_KEYS = ("controller", "agent_runtime", "base", "judge", "e2e")
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECTION = re.compile(r"^(?P<indent>\s*)templates\s*:\s*(?:#.*)?$")
_VALUE = re.compile(
    r"^(?P<indent>\s+)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
    r"(?P<value>[^#]+?)(?:\s+#.*)?$"
)


@dataclass(frozen=True)
class TemplateAliases:
    """Non-secret E2B aliases resolved from the private operator config."""

    controller: str = "lda-controller"
    agent_runtime: str = "lda-agent-runtime"
    base: str = "lda-base"
    judge: str = "lda-judge"
    e2e: str = "lda-e2e"

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if not isinstance(value, str) or not _ALIAS.fullmatch(value):
                raise ValueError(f"invalid E2B template alias for {key}: {value!r}")

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def alias_for(self, name: str) -> str:
        key = name.removeprefix("lda-").replace("-", "_")
        if key not in TEMPLATE_KEYS:
            raise ValueError(f"unknown template: {name}")
        return str(getattr(self, key))

    @classmethod
    def from_mapping(cls, values: Mapping[str, object] | None) -> "TemplateAliases":
        if values is None:
            return cls()
        unknown = set(values) - set(TEMPLATE_KEYS)
        if unknown:
            raise ValueError("unknown templates config keys: " + ", ".join(sorted(unknown)))
        return cls(**{key: str(value) for key, value in values.items()})

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "TemplateAliases":
        configured = path or os.environ.get("LDA_CONFIG_FILE")
        if configured is None:
            configured = Path.cwd() / "configs" / "lda.yaml"
        config = Path(configured).expanduser()
        if not config.is_file():
            return cls()

        values: dict[str, str] = {}
        section_indent: int | None = None
        for raw_line in config.read_text(encoding="utf-8").splitlines():
            if section_indent is None:
                match = _SECTION.match(raw_line)
                if match:
                    section_indent = len(match.group("indent"))
                continue
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip())
            if indent <= section_indent:
                break
            match = _VALUE.match(raw_line)
            if not match:
                raise ValueError(f"invalid templates config line: {raw_line.strip()}")
            key = match.group("key")
            if key not in TEMPLATE_KEYS:
                raise ValueError(f"unknown templates config key: {key}")
            value = match.group("value").strip().strip("\"'")
            values[key] = value
        return cls.from_mapping(values)
