"""Pure monotonic configuration merge and capability resolution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .defaults import (
    BUILTIN_CONFIG,
    BUILTIN_DIAGNOSTICS,
    BUILTIN_MEMORY_TYPES,
    BUILTIN_SENSITIVE_PATHS,
    MAX_TIMEOUT_SECONDS,
)
from .models import CapabilitySet, ConfigConflict, ConfigDocument, FrozenConfig, sha256_canonical_config


def _document(value: dict[str, Any]) -> dict[str, Any]:
    return ConfigDocument.model_validate(value).model_dump(mode="json", exclude_none=True)


def _get(layer: dict[str, Any], section: str, field: str, fallback: Any) -> Any:
    return layer.get(section, {}).get(field, fallback)


def resolve_config(builtin: dict[str, Any], user: dict[str, Any], repo: dict[str, Any], mode: str) -> FrozenConfig:
    try:
        base = _document(deepcopy(builtin))
        user_doc = _document(deepcopy(user))
        repo_doc = _document(deepcopy(repo))
        if mode not in {"real", "demo"}:
            raise ConfigConflict("unsupported mode")
        if repo_doc.get("mode") not in {None, mode}:
            raise ConfigConflict("repository cannot change execution mode")

        provenance: dict[str, str] = {}
        merged: dict[str, Any] = deepcopy(base)
        merged["schema_version"] = base["schema_version"]

        for section in ("llm", "tests", "limits", "patch", "memory"):
            merged.setdefault(section, {})
            for field, value in user_doc.get(section, {}).items():
                merged[section][field] = value
                provenance[f"{section}.{field}"] = "user"
            for field, value in repo_doc.get(section, {}).items():
                if field == "timeout_seconds":
                    continue
                if field in merged[section] and isinstance(value, int) and isinstance(merged[section][field], int):
                    if value > merged[section][field] and section == "limits":
                        raise ConfigConflict(f"repository broadens {section}.{field}")
                    merged[section][field] = min(merged[section][field], value) if section == "limits" else value
                else:
                    merged[section][field] = value
                provenance[f"{section}.{field}"] = "repo"

        user_timeout = _get(user_doc, "tests", "timeout_seconds", merged["tests"]["timeout_seconds"])
        repo_timeout = _get(repo_doc, "tests", "timeout_seconds", user_timeout)
        if repo_timeout > MAX_TIMEOUT_SECONDS or user_timeout > MAX_TIMEOUT_SECONDS:
            raise ConfigConflict("timeout exceeds hard limit")
        merged["tests"]["timeout_seconds"] = min(base["tests"]["timeout_seconds"], user_timeout, repo_timeout)
        if repo_timeout != base["tests"]["timeout_seconds"]:
            provenance["tests.timeout_seconds"] = "repo"
        elif user_timeout != base["tests"]["timeout_seconds"]:
            provenance["tests.timeout_seconds"] = "user"

        base_paths = base.get("paths", {})
        user_paths = user_doc.get("paths", {})
        repo_paths = repo_doc.get("paths", {})
        merged["paths"] = {
            "protected": sorted(set(base_paths.get("protected", ())) | set(user_paths.get("protected", ())) | set(repo_paths.get("protected", ()))),
            "sensitive": sorted(set(BUILTIN_SENSITIVE_PATHS) | set(user_paths.get("sensitive", ())) | set(repo_paths.get("sensitive", ()))),
        }
        provenance["paths.protected"] = "repo" if repo_paths.get("protected") else ("user" if user_paths.get("protected") else "builtin")
        provenance["paths.sensitive"] = "repo" if repo_paths.get("sensitive") else ("user" if user_paths.get("sensitive") else "builtin")

        allowed = set(BUILTIN_DIAGNOSTICS)
        if "allowed_commands" in user_doc.get("diagnostics", {}):
            allowed &= set(user_doc["diagnostics"]["allowed_commands"])
            provenance["diagnostics.allowed_commands"] = "user"
        if "allowed_commands" in repo_doc.get("diagnostics", {}):
            allowed &= set(repo_doc["diagnostics"]["allowed_commands"])
            provenance["diagnostics.allowed_commands"] = "repo"
        if not allowed and mode == "real":
            raise ConfigConflict("diagnostic whitelist intersection is empty")
        merged["diagnostics"] = {"allowed_commands": sorted(allowed)}

        merged["memory"]["allowed_types"] = sorted(set(BUILTIN_MEMORY_TYPES) & set(_get(user_doc, "memory", "allowed_types", BUILTIN_MEMORY_TYPES)) & set(_get(repo_doc, "memory", "allowed_types", BUILTIN_MEMORY_TYPES)))
        capabilities = CapabilitySet(mode=mode, openai_enabled=mode == "real", credentials_enabled=mode == "real", arbitrary_paths_enabled=mode == "real", diagnostic_ids=() if mode == "demo" else tuple(merged["diagnostics"]["allowed_commands"]), command_prefixes=("pytest", "python -m pytest") if mode == "real" else ("pytest",))
        frozen_data = {**merged, "mode": mode, "capabilities": capabilities.model_dump(mode="json"), "provenance": provenance, "sha256": "0" * 64}
        frozen_data["sha256"] = sha256_canonical_config(frozen_data)
        return FrozenConfig.model_validate(frozen_data)
    except ConfigConflict:
        raise
    except Exception as exc:
        raise ConfigConflict("configuration conflict") from exc
