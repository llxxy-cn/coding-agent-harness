from __future__ import annotations

import re
from pathlib import PurePosixPath

from .models import OperationType, PatchFacts, PatchFilePlan, PatchSnapshot, PreparedPatch, sha256


def _path(value: str) -> str | None:
    if value == "/dev/null":
        return None
    if value.startswith(("/", "\\")) or (len(value) > 1 and value[1] == ":") or "\x00" in value:
        raise ValueError("unsafe patch path")
    value = value.split("\t", 1)[0]
    if value.startswith(("a/", "b/")):
        value = value[2:]
    parts = value.replace("\\", "/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("unsafe patch path")
    return str(PurePosixPath(*parts))


def prepare(diff: bytes | str, snapshot: PatchSnapshot) -> PreparedPatch:
    raw = diff.encode("utf-8") if isinstance(diff, str) else diff
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise ValueError("diff must be LF-only UTF-8 with final newline")
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    plans = []
    i = 0
    added = deleted = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        old_path = _path(lines[i][4:].rstrip("\n"))
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError("missing new path")
        new_path = _path(lines[i][4:].rstrip("\n"))
        i += 1
        path = new_path or old_path
        if path is None or path in {plan.path for plan in plans}:
            raise ValueError("duplicate patch path")
        old = snapshot.files.get(old_path) if old_path else None
        if old_path and old is None and new_path == old_path:
            raise ValueError("modify target missing")
        if old_path is None and new_path in snapshot.files:
            raise ValueError("create target exists")
        if new_path is None and old is None:
            raise ValueError("delete target missing")
        hunk = []
        while i < len(lines) and not lines[i].startswith("--- "):
            if lines[i].startswith("@@"):
                i += 1
                continue
            line = lines[i]
            if line.startswith((" ", "+", "-")):
                hunk.append(line)
                if line.startswith("+"):
                    added += 1
                elif line.startswith("-"):
                    deleted += 1
            elif line.startswith("diff --git "):
                break
            elif line.strip() and not line.startswith("\\ No newline"):
                raise ValueError("invalid hunk")
            i += 1
        old_lines = [line[1:] for line in hunk if line.startswith((" ", "-"))]
        new_lines = [line[1:] for line in hunk if line.startswith((" ", "+"))]
        old_text = "".join(old_lines) if old_lines else ""
        if old is not None and old.decode("utf-8") != old_text:
            raise ValueError("context mismatch")
        post = "".join(new_lines).encode("utf-8") if new_path else None
        operation = OperationType.CREATE if old_path is None else OperationType.DELETE if new_path is None else OperationType.MODIFY
        plans.append(PatchFilePlan(path, operation, sha256(old), sha256(post), old, post))
    if not plans:
        raise ValueError("empty diff")
    facts = PatchFacts(len(plans), added, deleted, any(p.path.startswith("tests/") or p.path.endswith("_test.py") or p.path.endswith("/conftest.py") for p in plans), any(p.path.startswith("harness-data/") or p.path.startswith(".env") or p.path.endswith((".pem", ".key")) for p in plans))
    return PreparedPatch(tuple(plans), facts)
