"""Contract tests for the frozen Action protocol in SPEC section 9."""

from __future__ import annotations

import pytest

from coding_agent_harness.domain.actions import (
    ApplyPatchAction,
    GitDiffAction,
    GitStatusAction,
    ListFilesAction,
    ReadFileAction,
    RequestHumanAction,
    RunDiagnosticAction,
    RunTestsAction,
    SearchCodeAction,
    parse_action,
)
from coding_agent_harness.domain.enums import ProtocolErrorCode
from coding_agent_harness.domain.models import ProtocolError, ValidatedAction


MESSAGES = {
    ProtocolErrorCode.INVALID_JSON: "Action must be a valid JSON object.",
    ProtocolErrorCode.INVALID_TOP_LEVEL: "Action must be a JSON object.",
    ProtocolErrorCode.MISSING_TYPE: "Action field 'type' is required.",
    ProtocolErrorCode.INVALID_TYPE: "Action field 'type' must match ^[a-z][a-z0-9_]{0,63}$.",
    ProtocolErrorCode.UNKNOWN_ACTION: "Action type is not supported.",
    ProtocolErrorCode.SCHEMA_VIOLATION: "Action fields do not match the required schema.",
}


def assert_error(raw: object, code: ProtocolErrorCode) -> None:
    result = parse_action(raw)  # type: ignore[arg-type]
    assert result == ProtocolError(code=code, sanitized_message=MESSAGES[code])


@pytest.mark.parametrize(
    ("raw", "expected_type"),
    [
        ({"type": "list_files", "path": ".", "recursive": False}, ListFilesAction),
        ({"type": "read_file", "path": "README.md"}, ReadFileAction),
        ({"type": "search_code", "path": "src", "query": "name", "case_sensitive": True}, SearchCodeAction),
        ({"type": "apply_patch", "diff": "unparsed content\n"}, ApplyPatchAction),
        ({"type": "run_tests", "scope": "full", "targets": []}, RunTestsAction),
        ({"type": "git_diff"}, GitDiffAction),
        ({"type": "git_status"}, GitStatusAction),
        ({"type": "run_diagnostic", "diagnostic_id": "ruff_check", "arguments": []}, RunDiagnosticAction),
        ({"type": "request_human", "reason": "Please clarify safely."}, RequestHumanAction),
    ],
)
def test_nine_actions_parse_to_exact_frozen_concrete_types(raw, expected_type):
    action = parse_action(raw)
    assert type(action) is expected_type
    assert isinstance(action, ValidatedAction)
    with pytest.raises(Exception):
        action.type = "changed"


def test_base_is_abstract_and_finish_is_unknown():
    with pytest.raises(TypeError):
        ValidatedAction()
    assert_error({"type": "finish"}, ProtocolErrorCode.UNKNOWN_ACTION)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("{", ProtocolErrorCode.INVALID_JSON),
        ('{"type":"git_status"} trailing', ProtocolErrorCode.INVALID_JSON),
        ('{"type":"git_status","type":"git_diff"}', ProtocolErrorCode.INVALID_JSON),
        ('{"type":"git_status","x":NaN}', ProtocolErrorCode.INVALID_JSON),
        ('{"type":"git_status","x":Infinity}', ProtocolErrorCode.INVALID_JSON),
        ([], ProtocolErrorCode.INVALID_TOP_LEVEL),
        (None, ProtocolErrorCode.INVALID_TOP_LEVEL),
        ({}, ProtocolErrorCode.MISSING_TYPE),
        ({"type": 1}, ProtocolErrorCode.INVALID_TYPE),
        ({"type": "Git"}, ProtocolErrorCode.INVALID_TYPE),
        ({"type": "future_action"}, ProtocolErrorCode.UNKNOWN_ACTION),
        ({"type": "git_status", "extra": True}, ProtocolErrorCode.SCHEMA_VIOLATION),
    ],
)
def test_parser_priority_strict_json_and_fixed_sanitized_errors(raw, code):
    assert_error(raw, code)


def test_dict_input_is_unchanged_and_nested_arrays_are_defensively_frozen():
    raw = {"type": "run_tests", "scope": "focused", "targets": ["tests/test_ok.py"]}
    action = parse_action(raw)
    assert isinstance(action, RunTestsAction)
    assert action.targets == ("tests/test_ok.py",)
    assert raw["targets"] == ["tests/test_ok.py"]


@pytest.mark.parametrize("path", [".", "src/a.py", "dir with space/a.py", "../deferred.py"])
def test_common_path_preserves_schema_accepted_values(path):
    action = parse_action({"type": "read_file", "path": path})
    assert isinstance(action, ReadFileAction) and action.path == path


@pytest.mark.parametrize("path", ["", "a\x00b", "/absolute", "a" * 4097])
def test_common_path_rejects_only_schema_level_errors(path):
    assert_error({"type": "list_files", "path": path, "recursive": False}, ProtocolErrorCode.SCHEMA_VIOLATION)


@pytest.mark.parametrize("recursive", [0, 1, "false", None])
def test_list_files_requires_strict_bool(recursive):
    assert_error({"type": "list_files", "path": ".", "recursive": recursive}, ProtocolErrorCode.SCHEMA_VIOLATION)


def test_read_file_line_pair_matrix_uses_strict_inclusive_bounds():
    valid = parse_action({"type": "read_file", "path": "a.py", "start_line": 1, "end_line": 1_000_000})
    assert isinstance(valid, ReadFileAction)
    for start, end in [(1, None), (None, 1), (0, 1), (2, 1), (1, 1_000_001), (True, 1), (1.0, 1), ("1", 1)]:
        assert_error({"type": "read_file", "path": "a.py", "start_line": start, "end_line": end}, ProtocolErrorCode.SCHEMA_VIOLATION)


@pytest.mark.parametrize("query", ["", "   ", "a\x00b", "a\rb", "a\nb", "x" * 1001])
def test_search_query_is_literal_bounded_and_control_free(query):
    assert_error({"type": "search_code", "path": ".", "query": query, "case_sensitive": False}, ProtocolErrorCode.SCHEMA_VIOLATION)


@pytest.mark.parametrize("diff", ["", "   ", "a\x00b\n", "a\rb\n", "no-lf", "\ud800\n"])
def test_apply_patch_enforces_only_frozen_string_protocol(diff):
    assert_error({"type": "apply_patch", "diff": diff}, ProtocolErrorCode.SCHEMA_VIOLATION)


def test_apply_patch_preserves_bytes_and_boundary_without_parsing():
    diff = "deliberately not a diff header\n"
    action = parse_action({"type": "apply_patch", "diff": diff})
    assert isinstance(action, ApplyPatchAction) and action.diff == diff
    assert isinstance(parse_action({"type": "apply_patch", "diff": "a" * 2_097_151 + "\n"}), ApplyPatchAction)
    assert_error({"type": "apply_patch", "diff": "a" * 2_097_152 + "\n"}, ProtocolErrorCode.SCHEMA_VIOLATION)


def test_run_tests_scope_array_count_duplicate_and_order_contract():
    assert isinstance(parse_action({"type": "run_tests", "scope": "full", "targets": []}), RunTestsAction)
    ordered = ["tests/test_b.py", "tests/test_a.py"]
    action = parse_action({"type": "run_tests", "scope": "focused", "targets": ordered})
    assert isinstance(action, RunTestsAction) and action.targets == tuple(ordered)
    for targets in [["tests/test_a.py"], (), [], ["tests/test_a.py"] * 2, [f"tests/test_{i}.py" for i in range(33)]]:
        scope = "full" if targets == ["tests/test_a.py"] else "focused"
        assert_error({"type": "run_tests", "scope": scope, "targets": targets}, ProtocolErrorCode.SCHEMA_VIOLATION)


@pytest.mark.parametrize("target", ["tests/test_file.py", "tests/a b/test_file.py::TestThing::test_method", "tests/test_file.py::test_case[param id :: $()!]", "tests/test_file.py::Δοκιμή"])
def test_focused_node_id_accepts_frozen_subset(target):
    assert isinstance(parse_action({"type": "run_tests", "scope": "focused", "targets": [target]}), RunTestsAction)


@pytest.mark.parametrize("target", ["", "   ", ".", "-k", "/tests/test_a.py", '"tests/test_a.py"', "tests/test_a.txt", "tests/*.py", " tests/test_a.py", "tests/test_a.py ", "tests/test_a.py::", "tests/test_a.py::::x", "tests/test_a.py::not valid", "tests/test_a.py::x[]", "tests/test_a.py::x[a[b]", "tests/test_a.py::x[a]tail", "tests/test_a.py::x[a]::more"])
def test_focused_node_id_rejects_undefined_forms(target):
    assert_error({"type": "run_tests", "scope": "focused", "targets": [target]}, ProtocolErrorCode.SCHEMA_VIOLATION)


@pytest.mark.parametrize("kind", ["git_diff", "git_status"])
def test_git_actions_are_type_only(kind):
    assert not isinstance(parse_action({"type": kind}), ProtocolError)
    assert_error({"type": kind, "ref": "HEAD"}, ProtocolErrorCode.SCHEMA_VIOLATION)


def test_diagnostic_id_arguments_and_execution_field_boundaries():
    action = parse_action({"type": "run_diagnostic", "diagnostic_id": "ruff_check", "arguments": ["", "--flag", "two words"]})
    assert isinstance(action, RunDiagnosticAction) and action.arguments == ("", "--flag", "two words")
    for diagnostic_id in ["", "A", "a-b", "_a", "a" * 65, "å"]:
        assert_error({"type": "run_diagnostic", "diagnostic_id": diagnostic_id, "arguments": []}, ProtocolErrorCode.SCHEMA_VIOLATION)
    for extra in ["command", "argv", "executable", "shell", "cwd", "env", "timeout"]:
        assert_error({"type": "run_diagnostic", "diagnostic_id": "check", "arguments": [], extra: "x"}, ProtocolErrorCode.SCHEMA_VIOLATION)


def test_request_human_preserves_safe_multiline_reason():
    reason = "Cannot continue safely.\nPlease clarify the intended behavior."
    action = parse_action({"type": "request_human", "reason": reason})
    assert isinstance(action, RequestHumanAction) and action.reason == reason


@pytest.mark.parametrize(
    "reason",
    ["", "   ", " leading", "trailing ", "tab\there", "cr\rhere", "\x00", "\x1b", "\x7f", "\x80", "\u2028", "\u2029", "\ud800", "x" * 4001, "😀" * 4097],
    ids=["empty", "blank", "leading", "trailing", "tab", "cr", "nul", "escape", "del", "c1", "line-separator", "paragraph-separator", "surrogate", "character-limit", "utf8-byte-limit"],
)
def test_request_human_rejects_controls_whitespace_and_bounds(reason):
    assert_error({"type": "request_human", "reason": reason}, ProtocolErrorCode.SCHEMA_VIOLATION)


@pytest.mark.parametrize(
    ("base", "forbidden"),
    [
        ({"type": "list_files", "path": ".", "recursive": False}, "glob"),
        ({"type": "search_code", "path": ".", "query": "x", "case_sensitive": False}, "regex"),
        ({"type": "apply_patch", "diff": "x\n"}, "artifact_ref"),
        ({"type": "run_tests", "scope": "full", "targets": []}, "command"),
        ({"type": "request_human", "reason": "Need input."}, "resume_state"),
    ],
)
def test_actions_forbid_llm_control_fields(base, forbidden):
    assert_error(base | {forbidden: "x"}, ProtocolErrorCode.SCHEMA_VIOLATION)
