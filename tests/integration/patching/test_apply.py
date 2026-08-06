from pathlib import Path

from coding_agent_harness.patching.applier import apply
from coding_agent_harness.patching.models import PatchSnapshot
from coding_agent_harness.patching.parser import prepare


def test_apply_writes_modify_create_delete_only_after_prevalidation(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes(b"old\n")
    snapshot = PatchSnapshot.from_root(tmp_path)
    diff = b"--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    prepared = prepare(diff, snapshot)
    result = apply(prepared, authorization=True, root=tmp_path)
    assert result.ok
    assert (tmp_path / "app.py").read_bytes() == b"new\n"
