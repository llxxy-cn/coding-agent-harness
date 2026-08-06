from pathlib import Path

import hashlib

from coding_agent_harness.patching.applier import apply
from coding_agent_harness.patching.models import PatchSnapshot
from coding_agent_harness.patching.parser import prepare


def test_preimage_drift_returns_conflict_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_bytes(b"old\n")
    prepared = prepare(b"--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-old\n+new\n", PatchSnapshot.from_root(tmp_path))
    path.write_bytes(b"external\n")
    result = apply(prepared, authorization=True, root=tmp_path)
    assert not result.ok and result.error_code == "conflict"
    assert path.read_bytes() == b"external\n"


def test_second_file_failure_compensates_first_without_running_pytest(tmp_path: Path) -> None:
    for name in ("one.txt", "two.txt", "three.txt"):
        (tmp_path / name).write_bytes((name + " old\n").encode())
    snapshot = PatchSnapshot.from_root(tmp_path)
    diff = b"--- a/one.txt\n+++ b/one.txt\n@@ -1,1 +1,1 @@\n-one.txt old\n+one.txt new\n--- a/two.txt\n+++ b/two.txt\n@@ -1,1 +1,1 @@\n-two.txt old\n+two.txt new\n--- a/three.txt\n+++ b/three.txt\n@@ -1,1 +1,1 @@\n-three.txt old\n+three.txt new\n"
    prepared = prepare(diff, snapshot)
    attempts = []
    def replace(source, target):
        attempts.append(target.name)
        if target.name == "two.txt":
            raise OSError("injected once")
        target.write_bytes(Path(source).read_bytes())
    result = apply(prepared, authorization=True, root=tmp_path, replace_callback=replace)
    assert not result.ok and result.error_code == "apply_failed"
    assert result.rollback_result.ok
    assert attempts == ["one.txt", "two.txt"]
    for name in ("one.txt", "two.txt", "three.txt"):
        expected = snapshot.files[name]
        assert (tmp_path / name).read_bytes() == expected
    assert hashlib.sha256((tmp_path / "one.txt").read_bytes()).hexdigest() == hashlib.sha256(snapshot.files["one.txt"]).hexdigest()


def test_compensation_refuses_external_change(tmp_path: Path) -> None:
    path = tmp_path / "one.txt"
    path.write_bytes(b"old\n")
    prepared = prepare(b"--- a/one.txt\n+++ b/one.txt\n@@ -1,1 +1,1 @@\n-old\n+new\n", PatchSnapshot.from_root(tmp_path))
    changed = []
    def replace(source, target):
        target.write_bytes(Path(source).read_bytes())
        changed.append(target)
    def failing(source, target):
        replace(source, target)
        path.write_bytes(b"external\n")
        raise OSError("stop")
    result = apply(prepared, authorization=True, root=tmp_path, replace_callback=failing)
    assert not result.ok and result.rollback_result.error_code == "conflict"
    assert path.read_bytes() == b"external\n"
