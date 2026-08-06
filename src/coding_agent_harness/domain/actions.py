"""Strict parsing and immutable schemas for the nine supported Actions."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from .enums import ProtocolErrorCode
from .errors import PROTOCOL_ERROR_MESSAGES
from .models import ProtocolError, ValidatedAction, _strict_utf8


_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIAGNOSTIC_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _validate_common_path(path: str) -> str:
    if not 1 <= len(path) <= 4096 or "\x00" in path or path.startswith("/"):
        raise ValueError("invalid schema-level path")
    return path


def _require_json_array(value: object) -> object:
    if not isinstance(value, list):
        raise ValueError("value must be a JSON array")
    return value


class ListFilesAction(ValidatedAction):
    type: Literal["list_files"]
    path: str
    recursive: StrictBool

    _path = field_validator("path")(_validate_common_path)


class ReadFileAction(ValidatedAction):
    type: Literal["read_file"]
    path: str
    start_line: StrictInt | None = None
    end_line: StrictInt | None = None

    _path = field_validator("path")(_validate_common_path)

    @model_validator(mode="after")
    def validate_lines(self) -> ReadFileAction:
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("line bounds must be paired")
        if self.start_line is not None and not (1 <= self.start_line <= self.end_line <= 1_000_000):
            raise ValueError("line bounds are invalid")
        return self


class SearchCodeAction(ValidatedAction):
    type: Literal["search_code"]
    path: str
    query: StrictStr
    case_sensitive: StrictBool

    _path = field_validator("path")(_validate_common_path)

    @field_validator("query")
    @classmethod
    def validate_query(cls, query: str) -> str:
        if not 1 <= len(query) <= 1000 or not query.strip() or any(char in query for char in "\x00\r\n"):
            raise ValueError("query is invalid")
        return query


class ApplyPatchAction(ValidatedAction):
    type: Literal["apply_patch"]
    diff: StrictStr

    @field_validator("diff")
    @classmethod
    def validate_diff(cls, diff: str) -> str:
        encoded = _strict_utf8(diff)
        if not diff.strip() or "\x00" in diff or "\r" in diff or not diff.endswith("\n") or not 1 <= len(encoded) <= 2_097_152:
            raise ValueError("diff protocol is invalid")
        return diff


def _validate_focused_target(target: str) -> None:
    _strict_utf8(target)
    if not 1 <= len(target) <= 4096 or not target.strip() or target != target.strip() or any(char in target for char in "\x00\r\n"):
        raise ValueError("focused target text is invalid")
    if target == "." or target.startswith(("-", "/", "'", '"')) or "*" in target or "?" in target:
        raise ValueError("focused target form is invalid")
    parameter: str | None = None
    selector_source = target
    if "[" in target or "]" in target:
        opening = target.rfind("[")
        if opening < 0 or not target.endswith("]") or "]" in target[opening:-1] or "[" in target[opening + 1 :]:
            raise ValueError("parameter suffix is invalid")
        parameter = target[opening + 1 : -1]
        selector_source = target[:opening]
        if not 1 <= len(parameter) <= 512 or any(char in parameter for char in "[]\x00\r\n"):
            raise ValueError("parameter id is invalid")
    pieces = selector_source.split("::")
    path = pieces[0]
    if not path.endswith(".py"):
        raise ValueError("focused target path must be Python")
    selectors = pieces[1:]
    if any(not selector for selector in selectors):
        raise ValueError("selector cannot be empty")
    if parameter is not None and not selectors:
        raise ValueError("parameter suffix requires a selector")
    for selector in selectors:
        if not selector.isidentifier():
            raise ValueError("selector is invalid")


class RunTestsAction(ValidatedAction):
    type: Literal["run_tests"]
    scope: Literal["full", "focused"]
    targets: tuple[StrictStr, ...]

    @field_validator("targets", mode="before")
    @classmethod
    def targets_must_be_array(cls, value: object) -> object:
        return _require_json_array(value)

    @model_validator(mode="after")
    def validate_targets(self) -> RunTestsAction:
        if self.scope == "full":
            if self.targets:
                raise ValueError("full scope targets must be empty")
            return self
        if not 1 <= len(self.targets) <= 32 or len(set(self.targets)) != len(self.targets):
            raise ValueError("focused target count or duplicates are invalid")
        total = 0
        for target in self.targets:
            _validate_focused_target(target)
            total += len(_strict_utf8(target))
        if total > 32768:
            raise ValueError("focused target bytes are invalid")
        return self


class GitDiffAction(ValidatedAction):
    type: Literal["git_diff"]


class GitStatusAction(ValidatedAction):
    type: Literal["git_status"]


class RunDiagnosticAction(ValidatedAction):
    type: Literal["run_diagnostic"]
    diagnostic_id: StrictStr
    arguments: tuple[StrictStr, ...]

    @field_validator("diagnostic_id")
    @classmethod
    def validate_diagnostic_id(cls, value: str) -> str:
        if not _DIAGNOSTIC_PATTERN.fullmatch(value) or not value.isascii():
            raise ValueError("diagnostic id is invalid")
        return value

    @field_validator("arguments", mode="before")
    @classmethod
    def arguments_must_be_array(cls, value: object) -> object:
        return _require_json_array(value)

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, arguments: tuple[str, ...]) -> tuple[str, ...]:
        if len(arguments) > 32:
            raise ValueError("too many diagnostic arguments")
        total = 0
        for argument in arguments:
            encoded = _strict_utf8(argument)
            if len(argument) > 4096 or any(char in argument for char in "\x00\r\n"):
                raise ValueError("diagnostic argument is invalid")
            total += len(encoded)
        if total > 32768:
            raise ValueError("diagnostic argument bytes are invalid")
        return arguments


class RequestHumanAction(ValidatedAction):
    type: Literal["request_human"]
    reason: StrictStr

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, reason: str) -> str:
        encoded = _strict_utf8(reason)
        if not 1 <= len(reason) <= 4000 or len(encoded) > 16384 or not reason.strip() or reason != reason.strip() or any(char in "\r\u2028\u2029" for char in reason):
            raise ValueError("human reason is invalid")
        if any(unicodedata.category(char) == "Cc" and char != "\n" for char in reason):
            raise ValueError("human reason contains a control")
        return reason


ActionUnion = (
    ListFilesAction
    | ReadFileAction
    | SearchCodeAction
    | ApplyPatchAction
    | RunTestsAction
    | GitDiffAction
    | GitStatusAction
    | RunDiagnosticAction
    | RequestHumanAction
)

_ACTION_TYPES = {
    "list_files": ListFilesAction,
    "read_file": ReadFileAction,
    "search_code": SearchCodeAction,
    "apply_patch": ApplyPatchAction,
    "run_tests": RunTestsAction,
    "git_diff": GitDiffAction,
    "git_status": GitStatusAction,
    "run_diagnostic": RunDiagnosticAction,
    "request_human": RequestHumanAction,
}


def _protocol_error(code: ProtocolErrorCode) -> ProtocolError:
    return ProtocolError(code=code, sanitized_message=PROTOCOL_ERROR_MESSAGES[code])


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite constant {value}")


def parse_action(raw: str | dict[str, object]) -> ValidatedAction | ProtocolError:
    if isinstance(raw, str):
        try:
            value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite)
        except Exception:
            return _protocol_error(ProtocolErrorCode.INVALID_JSON)
    elif isinstance(raw, dict):
        value = raw.copy()
    else:
        return _protocol_error(ProtocolErrorCode.INVALID_TOP_LEVEL)
    if not isinstance(value, dict):
        return _protocol_error(ProtocolErrorCode.INVALID_TOP_LEVEL)
    if "type" not in value:
        return _protocol_error(ProtocolErrorCode.MISSING_TYPE)
    action_type = value["type"]
    if not isinstance(action_type, str) or not _TYPE_PATTERN.fullmatch(action_type):
        return _protocol_error(ProtocolErrorCode.INVALID_TYPE)
    model = _ACTION_TYPES.get(action_type)
    if model is None:
        return _protocol_error(ProtocolErrorCode.UNKNOWN_ACTION)
    try:
        return model.model_validate(value)
    except Exception:
        return _protocol_error(ProtocolErrorCode.SCHEMA_VIOLATION)
