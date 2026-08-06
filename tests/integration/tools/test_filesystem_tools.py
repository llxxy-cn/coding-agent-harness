from pathlib import Path

import pytest

from coding_agent_harness.adapters.filesystem.local_filesystem import LocalFileSystem
from coding_agent_harness.domain.actions import ListFilesAction, ReadFileAction, SearchCodeAction


def test_local_filesystem_reads_lists_and_searches_bounded_text(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_bytes(b"needle\nother\n")
    fs = LocalFileSystem(tmp_path)
    listing = fs.execute(ListFilesAction(type="list_files", path="tests", recursive=True))
    assert listing.ok and any(item.path == "tests/test_example.py" for item in listing.payload.files)
    read = fs.execute(ReadFileAction(type="read_file", path="tests/test_example.py", start_line=1, end_line=1))
    assert read.ok and read.payload.text == "needle\n"
    found = fs.execute(SearchCodeAction(type="search_code", path="tests", query="needle", case_sensitive=True))
    assert found.ok and found.payload.matches[0].line == 1


def test_local_filesystem_rejects_binary_and_out_of_bound_without_open(tmp_path: Path) -> None:
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01")
    fs = LocalFileSystem(tmp_path)
    result = fs.execute(ReadFileAction(type="read_file", path="blob.bin"))
    assert not result.ok
    huge = tmp_path / "huge.txt"
    huge.write_bytes(b"x" * (512 * 1024 + 1))
    result = fs.execute(ReadFileAction(type="read_file", path="huge.txt"))
    assert result.ok and result.payload.truncated


def test_list_files_recursive_flag_and_deterministic_relative_sort(tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "z.txt").write_bytes(b"z")
    (tmp_path / "a.txt").write_bytes(b"a")
    fs = LocalFileSystem(tmp_path)
    direct = fs.execute(ListFilesAction(type="list_files", path=".", recursive=False))
    assert [entry.path for entry in direct.payload.files] == ["a.txt"]
    recursive = fs.execute(ListFilesAction(type="list_files", path=".", recursive=True))
    assert [entry.path for entry in recursive.payload.files] == ["a.txt", "b/z.txt"]


def test_read_payload_has_strict_resume_position(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_bytes(b"first\n" + b"x" * (512 * 1024 + 10))
    fs = LocalFileSystem(tmp_path)
    result = fs.execute(ReadFileAction(type="read_file", path="large.txt"))
    assert result.ok and result.payload.truncated
    assert isinstance(result.payload.next_start_line, int)
    short = fs.execute(ReadFileAction(type="read_file", path="large.txt", start_line=1, end_line=1))
    assert short.ok and short.payload.text == "first\n"
    assert short.payload.truncated is False
    assert short.payload.next_start_line is None


def test_search_is_literal_case_aware_bounded_and_deterministic(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"Needle\nneedle [x]\n")
    (tmp_path / "b.py").write_bytes(b"needle\n" * 210)
    fs = LocalFileSystem(tmp_path)
    sensitive = fs.execute(SearchCodeAction(type="search_code", path=".", query="needle [x]", case_sensitive=True))
    assert [match.path for match in sensitive.payload.matches] == ["a.py"]
    insensitive = fs.execute(SearchCodeAction(type="search_code", path=".", query="needle", case_sensitive=False))
    assert len(insensitive.payload.matches) == 200
    assert insensitive.payload.truncated
    assert [(m.path, m.line, m.column) for m in insensitive.payload.matches] == sorted((m.path, m.line, m.column) for m in insensitive.payload.matches)


def test_all_protected_test_assets_are_readable_and_searchable(tmp_path: Path) -> None:
    for name in ("tests/test_example.py", "test_example.py", "example_test.py", "conftest.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"needle\n")
    fs = LocalFileSystem(tmp_path)
    for name in ("tests/test_example.py", "test_example.py", "example_test.py", "conftest.py"):
        assert fs.execute(ReadFileAction(type="read_file", path=name)).ok
        assert fs.execute(SearchCodeAction(type="search_code", path=name, query="needle", case_sensitive=True)).ok
