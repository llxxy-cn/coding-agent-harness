"""Strict, non-interpolating TOML loader."""

from __future__ import annotations

import re
import tomllib
from typing import Any

from .models import ConfigDocument


def _reject_interpolation(value: Any) -> None:
    if isinstance(value, str) and re.search(r"\$\{[^}]*\}", value):
        raise ValueError("environment interpolation is forbidden")
    if isinstance(value, dict):
        for child in value.values():
            _reject_interpolation(child)
    elif isinstance(value, list):
        for child in value:
            _reject_interpolation(child)


def load_strict_toml(raw: bytes) -> dict[str, Any]:
    try:
        document = tomllib.loads(raw.decode("utf-8"))
        _reject_interpolation(document)
        validated = ConfigDocument.model_validate(document)
        return validated.model_dump(mode="json", exclude_none=True)
    except Exception as exc:
        raise ValueError("invalid strict configuration") from exc
