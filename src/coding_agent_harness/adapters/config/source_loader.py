from __future__ import annotations

from pathlib import Path

from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.loader import load_strict_toml
from coding_agent_harness.config.models import ConfigConflict, FrozenConfig
from coding_agent_harness.config.resolver import resolve_config


class ConfigSourceError(RuntimeError):
    pass


class LayeredConfigSource:
    def __init__(self, *, user_config: str | Path, repository_reader) -> None:
        self.user_config = Path(user_config)
        self.repository_reader = repository_reader

    def load(self, *, repository: str | Path, base_commit: str) -> FrozenConfig:
        try:
            user = self._optional_file(self.user_config)
            repo_raw = self.repository_reader(Path(repository).resolve(strict=True), base_commit)
            if repo_raw is not None and not isinstance(repo_raw, bytes):
                raise ValueError
            repo = {} if repo_raw is None else load_strict_toml(repo_raw)
            if repo.get("llm"):
                raise ConfigConflict("repository cannot select a provider or model")
            return resolve_config(BUILTIN_CONFIG, user, repo, "real")
        except (OSError, ValueError, ConfigConflict):
            raise ConfigSourceError("configuration is invalid") from None

    @staticmethod
    def _optional_file(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        if not path.is_file():
            raise ValueError
        return load_strict_toml(path.read_bytes())
