"""Strict layered configuration and frozen capabilities."""

from .defaults import BUILTIN_CONFIG
from .loader import load_strict_toml
from .models import CapabilitySet, ConfigConflict, ConfigDocument, ConfigProvenance, FrozenConfig, RepoConfig, UserConfig
from .resolver import resolve_config, sha256_canonical_config

__all__ = ["BUILTIN_CONFIG", "CapabilitySet", "ConfigConflict", "ConfigDocument", "ConfigProvenance", "FrozenConfig", "RepoConfig", "UserConfig", "load_strict_toml", "resolve_config", "sha256_canonical_config"]
