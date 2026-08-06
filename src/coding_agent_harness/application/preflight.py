from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


_MAX_GIT_OUTPUT = 65_536
_SAFE_ENV = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "LANG", "LC_ALL"})


class PreflightError(RuntimeError):
    pass


class VerifiedRepository(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root: Path
    identity_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    base_commit: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")

    @field_validator("root")
    @classmethod
    def absolute_directory(cls, value: Path) -> Path:
        resolved = value.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("repository root is invalid")
        return resolved


class RepositoryPreflight:
    def __init__(self, *, launcher: Callable) -> None:
        self.launcher = launcher

    def inspect(self, repository: str | Path, *, on_verified=None) -> VerifiedRepository:
        try:
            root = Path(repository).resolve(strict=True)
            if not root.is_dir():
                raise PreflightError("repository preflight failed")
        except (OSError, ValueError):
            raise PreflightError("repository preflight failed") from None

        shown_root = self._run(("git", "rev-parse", "--show-toplevel"), root, "repository preflight failed")
        try:
            verified_root = Path(shown_root).resolve(strict=True)
        except (OSError, ValueError):
            raise PreflightError("repository preflight failed") from None
        if verified_root != root:
            raise PreflightError("repository preflight failed")

        status = self._run(("git", "status", "--porcelain"), root, "repository preflight failed")
        if status.strip():
            raise PreflightError("repository has uncommitted changes")
        base_commit = self._run(("git", "rev-parse", "HEAD"), root, "repository preflight failed").strip()
        if len(base_commit) != 40 or any(char not in "0123456789abcdef" for char in base_commit):
            raise PreflightError("repository preflight failed")
        identity = hashlib.sha256(root.as_posix().encode("utf-8", errors="strict")).hexdigest()
        facts = VerifiedRepository(root=root, identity_sha256=identity, base_commit=base_commit)
        if on_verified is not None:
            on_verified(facts)
        return facts

    def _run(self, argv: tuple[str, ...], cwd: Path, message: str) -> str:
        env = {key: value for key, value in os.environ.items() if key.upper() in _SAFE_ENV}
        try:
            result = self.launcher(argv, cwd, False, env)
        except Exception:
            raise PreflightError(message) from None
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        if getattr(result, "returncode", 1) != 0 or not isinstance(stdout, str) or not isinstance(stderr, str):
            raise PreflightError(message)
        if len(stdout.encode("utf-8", errors="strict")) > _MAX_GIT_OUTPUT or len(stderr.encode("utf-8", errors="strict")) > _MAX_GIT_OUTPUT:
            raise PreflightError(message)
        return stdout.strip()
