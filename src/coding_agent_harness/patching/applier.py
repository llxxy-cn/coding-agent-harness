from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .models import AppliedPatch, ApplyFailure, PreparedPatch, sha256
from .rollback import rollback


class CompensationFailure:
    def __init__(self, error_code: str, message: str, rollback_result) -> None:
        self.ok = False
        self.error_code = error_code
        self.message = message
        self.rollback_result = rollback_result


def apply(prepared: PreparedPatch, authorization: object, root: str | Path, writer=None, replace_callback=None):
    if not authorization:
        return ApplyFailure(False, "unauthorized", "patch execution is not authorized")
    root = Path(root).resolve()
    for plan in prepared.files:
        path = root / plan.path
        if path.is_symlink():
            return ApplyFailure(False, "conflict", "symlink target rejected")
        actual = path.read_bytes() if path.exists() else None
        if sha256(actual) != plan.pre_image_sha256:
            return ApplyFailure(False, "conflict", "pre-image drift")
    changed = []
    try:
        for plan in prepared.files:
            path = root / plan.path
            changed.append(plan)
            if plan.operation.value == "delete":
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(plan.post_image or b"")
                    handle.flush()
                    os.fsync(handle.fileno())
                if replace_callback is None:
                    os.replace(name, path)
                else:
                    replace_callback(name, path)
        return AppliedPatch(True, tuple(changed))
    except OSError:
        compensable = []
        for plan in changed:
            path = root / plan.path
            current = path.read_bytes() if path.exists() else None
            current_hash = sha256(current)
            if current_hash == plan.pre_image_sha256:
                continue
            if current_hash == plan.post_image_sha256:
                compensable.append(plan)
                continue
            result = type("RollbackResult", (), {"ok": False, "error_code": "conflict"})()
            return CompensationFailure("unknown_outcome", "patch compensation conflicted", result)
        result = rollback(compensable, root)
        if not result.ok:
            return CompensationFailure("unknown_outcome", "patch compensation conflicted", result)
        return CompensationFailure("apply_failed", "patch application failed", result)
