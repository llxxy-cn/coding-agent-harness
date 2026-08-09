from __future__ import annotations

import os
import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePath

_PACKAGE_FILES: Traversable = files("coding_agent_harness.demo")


def resolve_repository_template(name: str) -> Path:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("repository template name must be a non-empty string")
    if name.startswith(("/", "\\")):
        raise ValueError("repository template name must not be absolute")
    if PurePath(name).is_absolute():
        raise ValueError("repository template name must not be absolute")
    parts = re.split(r"[\\/]", name)
    if ".." in parts:
        raise ValueError("repository template name must not escape package root")
    resources_root = Path(str(_PACKAGE_FILES)) / "resources"
    candidate = (resources_root / name).resolve()
    root = resources_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("repository template name escapes package root") from None
    if not candidate.is_dir():
        raise ValueError(f"repository template not found: {name}")
    for directory, directory_names, file_names in os.walk(
        candidate,
        followlinks=False,
    ):
        for entry_name in (*directory_names, *file_names):
            entry = (Path(directory) / entry_name).resolve()
            try:
                entry.relative_to(root)
            except ValueError:
                raise ValueError(
                    "repository template contains a path escaping package root"
                ) from None
    return candidate
