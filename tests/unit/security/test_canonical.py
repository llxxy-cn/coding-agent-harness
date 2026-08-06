from datetime import datetime, timezone
from enum import Enum
from uuid import UUID
import hashlib

import pytest

from coding_agent_harness.security.canonical import canonical_bytes, canonical_sha256


class Color(Enum):
    RED = "red"


def test_canonical_json_is_sorted_compact_and_typed() -> None:
    value = {"z": 1, "a": (Color.RED, UUID("123e4567-e89b-42d3-a456-426614174000")), "t": datetime(2024, 1, 2, tzinfo=timezone.utc)}
    assert canonical_bytes(value) == b'{"a":["red","123e4567-e89b-42d3-a456-426614174000"],"t":"2024-01-02T00:00:00Z","z":1}'
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})
    assert len(canonical_sha256(value)) == 64


def test_canonical_rejects_nonfinite_nonjson_and_nonutc() -> None:
    with pytest.raises(ValueError):
        canonical_bytes(float("nan"))
    with pytest.raises(TypeError):
        canonical_bytes(object())
    with pytest.raises(ValueError):
        canonical_bytes(datetime(2024, 1, 1))


def test_canonical_unicode_and_exact_digest() -> None:
    value = {"text": "中文🙂"}
    encoded = canonical_bytes(value)
    assert encoded == '{"text":"中文🙂"}'.encode("utf-8")
    assert canonical_sha256(value) == hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_rejects_each_nonfinite_float(value) -> None:
    with pytest.raises(ValueError):
        canonical_bytes(value)


def test_canonical_rejects_unknown_object_and_unstable_repr() -> None:
    class AddressObject:
        def __repr__(self):
            return "AddressObject at 0xdeadbeef"
    with pytest.raises(TypeError):
        canonical_bytes(AddressObject())
