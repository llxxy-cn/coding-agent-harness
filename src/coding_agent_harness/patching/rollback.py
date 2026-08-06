from dataclasses import dataclass


@dataclass(frozen=True)
class RollbackResult:
    ok: bool
    error_code: str | None = None


def rollback(changed, root, replace_callback=None) -> RollbackResult:
    from pathlib import Path
    from .models import sha256
    root = Path(root)
    for plan in reversed(changed):
        path = root / plan.path
        current = path.read_bytes() if path.exists() else None
        if sha256(current) != plan.post_image_sha256:
            return RollbackResult(False, "conflict")
        if plan.pre_image is None:
            if path.exists():
                path.unlink()
        else:
            if replace_callback is None:
                path.write_bytes(plan.pre_image)
            else:
                replace_callback(plan.pre_image, path)
    return RollbackResult(True)

__all__ = ["RollbackResult", "rollback"]
