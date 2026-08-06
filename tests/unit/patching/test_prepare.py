from pathlib import Path

import pytest

from coding_agent_harness.patching.parser import prepare
from coding_agent_harness.patching.models import PatchSnapshot


def test_prepare_modify_create_delete_is_pure_and_hashes_files() -> None:
    snapshot = PatchSnapshot(files={"src/app.py": b"old = 1\nkeep = True\n", "src/remove.py": b"remove = True\n"})
    diff = Path("tests/fixtures/patches/modify_create_delete.diff").read_bytes()
    prepared = prepare(diff, snapshot)
    assert [file.operation.value for file in prepared.files] == ["modify", "create", "delete"]
    assert prepared.facts.file_count == 3
    assert prepared.facts.added_lines == 2 and prepared.facts.deleted_lines == 2
    modify, create, delete = prepared.files
    for digest in (modify.pre_image_sha256, modify.post_image_sha256, create.post_image_sha256, delete.pre_image_sha256):
        assert digest is not None and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
    assert create.pre_image_sha256 is None
    assert modify.pre_image_sha256 != modify.post_image_sha256
    assert delete.post_image_sha256 is None
    assert snapshot.files["src/app.py"] == b"old = 1\nkeep = True\n"


def test_protected_test_asset_prepares_without_writing() -> None:
    snapshot = PatchSnapshot(files={"tests/test_example.py": b"old = True\n"})
    prepared = prepare(Path("tests/fixtures/patches/protected_test.diff").read_bytes(), snapshot)
    assert prepared.facts.touches_test_assets is True
    assert snapshot.files["tests/test_example.py"] == b"old = True\n"


@pytest.mark.parametrize("diff", [b"--- /etc/passwd\n+++ b/x\n", b"--- a/x\r\n+++ b/x\r\n", b"GIT binary patch\n"])
def test_prepare_rejects_unsafe_or_non_text_diff(diff: bytes) -> None:
    with pytest.raises(ValueError):
        prepare(diff, PatchSnapshot(files={"x": b"x\n"}))
