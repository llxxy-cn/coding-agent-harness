"""Bounded test-execution port."""

from typing import Protocol, TypeVar, runtime_checkable


TestRequestT = TypeVar("TestRequestT")
TestExecutionT = TypeVar("TestExecutionT")


@runtime_checkable
class TestRunner(Protocol[TestRequestT, TestExecutionT]):
    def run(self, request: TestRequestT) -> TestExecutionT: ...
