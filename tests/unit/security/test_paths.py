from pathlib import Path

import pytest

from coding_agent_harness.security.paths import normalize_relative_path, resolve_guarded_path


def test_paths_allow_worktree_relative_and_test_assets(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text("value = 1\n", encoding="utf-8")
    facts = resolve_guarded_path(tmp_path, "tests/test_example.py")
    assert facts.relative_path == "tests/test_example.py"
    assert normalize_relative_path("test_example.py") == "test_example.py"


@pytest.mark.parametrize("value", ["C:\\repo\\x.py", "\\\\server\\share\\x.py", "/etc/passwd", "../escape", "a/../../escape", "bad\x00name", ".env", ".env.local", "id_rsa", "harness-data/x"])
def test_paths_reject_absolute_escape_nul_and_sensitive_values(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError):
        resolve_guarded_path(tmp_path, value)


def test_symlink_component_is_rejected_before_open(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-task6.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires SeCreateSymbolicLinkPrivilege")
        raise
    with pytest.raises(ValueError):
        resolve_guarded_path(tmp_path, "link")
