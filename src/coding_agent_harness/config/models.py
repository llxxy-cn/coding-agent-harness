"""Strict configuration models and immutable resolved configuration."""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


class ConfigConflict(ValueError):
    """Raised when layered configuration would broaden or become unsafe."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LLMConfig(_StrictModel):
    provider: StrictStr | None = None
    model: StrictStr | None = None


class TestsConfig(_StrictModel):
    default_command: tuple[StrictStr, ...] | None = None
    timeout_seconds: StrictInt | None = Field(default=None, ge=1)

    @field_validator("default_command", mode="before")
    @classmethod
    def command_array(cls, value: object) -> object:
        if value is not None and not isinstance(value, list):
            raise ValueError("default_command must be an array")
        return value


class LimitsConfig(_StrictModel):
    max_feedback_rounds: StrictInt | None = Field(default=None, ge=1)
    max_actions: StrictInt | None = Field(default=None, ge=1)
    history_window: StrictInt | None = Field(default=None, ge=1)
    max_no_progress: StrictInt | None = Field(default=None, ge=1)
    max_changed: StrictInt | None = Field(default=None, ge=1)
    max_process_output_bytes: StrictInt | None = Field(default=None, ge=1)
    max_llm_feedback_bytes: StrictInt | None = Field(default=None, ge=1)
    max_read_file_bytes: StrictInt | None = Field(default=None, ge=1)
    max_search_results: StrictInt | None = Field(default=None, ge=1)


class PatchConfig(_StrictModel):
    approval_file_threshold: StrictInt | None = Field(default=None, ge=1)
    approval_line_threshold: StrictInt | None = Field(default=None, ge=1)


class PathsConfig(_StrictModel):
    protected: tuple[StrictStr, ...] | None = None
    sensitive: tuple[StrictStr, ...] | None = None

    @field_validator("protected", "sensitive", mode="before")
    @classmethod
    def path_array(cls, value: object) -> object:
        if value is not None and not isinstance(value, list):
            raise ValueError("paths must be arrays")
        return value


class DiagnosticsConfig(_StrictModel):
    allowed_commands: tuple[StrictStr, ...] | None = None

    @field_validator("allowed_commands", mode="before")
    @classmethod
    def command_array(cls, value: object) -> object:
        if value is not None and not isinstance(value, list):
            raise ValueError("allowed_commands must be an array")
        return value


class MemoryConfig(_StrictModel):
    allowed_types: tuple[StrictStr, ...] | None = None
    max_items_per_context: StrictInt | None = Field(default=None, ge=1)
    max_context_bytes: StrictInt | None = Field(default=None, ge=1)

    @field_validator("allowed_types", mode="before")
    @classmethod
    def type_array(cls, value: object) -> object:
        if value is not None and not isinstance(value, list):
            raise ValueError("allowed_types must be an array")
        return value


class ConfigDocument(_StrictModel):
    schema_version: StrictInt = Field(default=1, ge=1)
    mode: StrictStr | None = None
    llm: LLMConfig = LLMConfig()
    tests: TestsConfig = TestsConfig()
    limits: LimitsConfig = LimitsConfig()
    patch: PatchConfig = PatchConfig()
    paths: PathsConfig = PathsConfig()
    diagnostics: DiagnosticsConfig = DiagnosticsConfig()
    memory: MemoryConfig = MemoryConfig()


UserConfig = ConfigDocument
RepoConfig = ConfigDocument


class CapabilitySet(_StrictModel):
    mode: StrictStr
    openai_enabled: bool
    credentials_enabled: bool
    arbitrary_paths_enabled: bool
    diagnostic_ids: tuple[StrictStr, ...]
    command_prefixes: tuple[StrictStr, ...]


class ConfigProvenance(dict[str, str]):
    """Per-field source mapping retained for UI and audit display."""


class FrozenConfig(_StrictModel):
    schema_version: StrictInt
    mode: StrictStr
    llm: LLMConfig
    tests: TestsConfig
    limits: LimitsConfig
    patch: PatchConfig
    paths: PathsConfig
    diagnostics: DiagnosticsConfig
    memory: MemoryConfig
    capabilities: CapabilitySet
    provenance: dict[StrictStr, StrictStr]
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    def canonical_mapping(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"sha256"})


def sha256_canonical_config(config: FrozenConfig | dict[str, Any]) -> str:
    """Hash only the deterministic FrozenConfig representation, not Task 8 JSON."""
    mapping = config.canonical_mapping() if isinstance(config, FrozenConfig) else {key: value for key, value in config.items() if key != "sha256"}
    payload = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
