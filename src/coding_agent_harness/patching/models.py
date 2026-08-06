from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class OperationType(str, Enum):
    MODIFY = "modify"
    CREATE = "create"
    DELETE = "delete"


@dataclass(frozen=True)
class PatchSnapshot:
    files: dict[str, bytes]

    @classmethod
    def from_root(cls, root: str | Path) -> "PatchSnapshot":
        root = Path(root)
        return cls({p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()})


@dataclass(frozen=True)
class PatchFilePlan:
    path: str
    operation: OperationType
    pre_image_sha256: str | None
    post_image_sha256: str | None
    pre_image: bytes | None
    post_image: bytes | None


@dataclass(frozen=True)
class PatchFacts:
    file_count: int
    added_lines: int
    deleted_lines: int
    touches_test_assets: bool
    touches_sensitive_paths: bool


@dataclass(frozen=True)
class PreparedPatch:
    files: tuple[PatchFilePlan, ...]
    facts: PatchFacts


@dataclass(frozen=True)
class AppliedPatch:
    ok: bool
    files: tuple[PatchFilePlan, ...]


@dataclass(frozen=True)
class ApplyFailure:
    ok: bool
    error_code: str
    message: str


def sha256(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()
