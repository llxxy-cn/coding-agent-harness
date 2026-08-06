from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path


SENSITIVE = (".env", ".env.*", "id_rsa", "id_ed25519", "*.pem", "*.key", "harness-data/**")


@dataclass(frozen=True)
class PathFacts:
    absolute_path: Path
    relative_path: str


def normalize_relative_path(value: str) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("invalid path")
    if value in {"", "."}:
        return ""
    if value.startswith(("/", "\\")) or (len(value) >= 2 and value[1] == ":") or value.startswith("//"):
        raise ValueError("absolute path rejected")
    parts = value.replace("\\", "/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path traversal rejected")
    normalized = "/".join(parts)
    if any(fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(parts[-1], pattern) for pattern in SENSITIVE):
        raise ValueError("sensitive path rejected")
    return normalized


def resolve_guarded_path(root: str | Path, value: str) -> PathFacts:
    relative = normalize_relative_path(value)
    root_path = Path(root).resolve()
    candidate = root_path.joinpath(*relative.split("/")) if relative else root_path
    current = root_path
    for component in relative.split("/") if relative else ():
        current = current / component
        if current.is_symlink():
            raise ValueError("symlink component rejected")
    resolved = candidate.resolve(strict=False)
    if root_path not in (resolved, *resolved.parents):
        raise ValueError("path escapes root")
    return PathFacts(resolved, relative)
