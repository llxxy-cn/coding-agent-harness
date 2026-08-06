from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


def _normalize(value):
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is not timezone.utc or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("datetime must be UTC")
        return value.strftime("%Y-%m-%dT%H:%M:%S") + ".%06dZ" % value.microsecond if value.microsecond else value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite number")
        return value
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("object keys must be strings")
        return {key: _normalize(value[key]) for key in sorted(value)}
    raise TypeError("unsupported canonical type")


def canonical_bytes(value) -> bytes:
    return json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_sha256(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
