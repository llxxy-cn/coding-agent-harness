from __future__ import annotations

import ast
from pathlib import Path


def test_application_package_has_no_concrete_infrastructure_imports() -> None:
    forbidden_modules = {"sqlite3", "openai", "keyring", "typer"}
    violations: list[str] = []
    root = Path("src/coding_agent_harness/application")
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "coding_agent_harness.adapters" or name.startswith("coding_agent_harness.adapters.") or name.split(".")[0] in forbidden_modules:
                    violations.append(f"{path.name}:{node.lineno}:{name}")
    assert violations == []
