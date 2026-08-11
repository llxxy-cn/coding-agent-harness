"""Server-rendered page contracts owned by the C2 template layer.

Response headers, cookies, CORS, and proxy-header handling belong to the C1
ASGI application. These tests deliberately exercise only the C2 Jinja seam.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.domain.enums import TestRunOutcome as RunOutcome
from coding_agent_harness.security.policy import PolicyOutcome, PolicyReasonCode
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    ExecutionTraceView,
    FeedbackProducedEvent,
    PolicyDecisionEvent,
    TerminalStatusEvent,
    TestCompletedEvent,
)

TEMPLATES = (
    Path(__file__).parents[3] / "src" / "coding_agent_harness" / "web" / "templates"
)


@dataclass
class _Control:
    tag: str
    attributes: tuple[tuple[str, str | None], ...]

    def values(self, name: str) -> tuple[str | None, ...]:
        return tuple(value for key, value in self.attributes if key == name)


@dataclass
class _Form:
    attributes: tuple[tuple[str, str | None], ...]
    controls: list[_Control] = field(default_factory=list)
    button_text: list[str] = field(default_factory=list)

    def values(self, name: str) -> tuple[str | None, ...]:
        return tuple(value for key, value in self.attributes if key == name)


class _ScenarioPageParser(HTMLParser):
    """Small test-only parser for form controls and visible button labels."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[_Form] = []
        self._current_form: _Form | None = None
        self._inside_button = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = tuple((name.lower(), value) for name, value in attrs)
        if tag == "form":
            self._current_form = _Form(attributes)
            self.forms.append(self._current_form)
            return
        if self._current_form is None:
            return
        if tag in {"input", "select", "textarea", "button"}:
            self._current_form.controls.append(_Control(tag, attributes))
        if tag == "button":
            self._inside_button = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "button":
            self._inside_button = False
        elif tag == "form":
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._current_form is not None and self._inside_button:
            self._current_form.button_text.append(data)


def _templates() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(("html", "xml")),
    )


def _render_scenarios(csrf_token: str = "csrf-test-token") -> str:
    registry = ScenarioRegistry()
    return (
        _templates()
        .get_template("scenarios.html")
        .render(
            csrf_token=csrf_token,
            scenarios=tuple(registry.get(scenario_id) for scenario_id in registry),
        )
    )


def _forms(page: str) -> list[_Form]:
    parser = _ScenarioPageParser()
    parser.feed(page)
    parser.close()
    return parser.forms


def _successful_named_controls(form: _Form) -> list[_Control]:
    return [
        control
        for control in form.controls
        if control.values("name") and not control.values("disabled")
    ]


def _visible_button_label(form: _Form) -> str:
    return " ".join("".join(form.button_text).split())


def test_scenario_forms_have_only_csrf_successful_controls_and_fixed_routes() -> None:
    """A new input, form, or route would let browser input escape the fixed demo."""
    forms = _forms(_render_scenarios())

    assert len(forms) == 3
    assert [(form.values("method"), form.values("action")) for form in forms] == [
        (("post",), ("/scenarios/feedback_success/runs",)),
        (("post",), ("/scenarios/governance_denied/runs",)),
        (("post",), ("/scenarios/human_review_pause/runs",)),
    ]
    assert [
        [
            (control.tag, control.values("name"), control.values("value"))
            for control in _successful_named_controls(form)
        ]
        for form in forms
    ] == [
        [("input", ("csrf_token",), ("csrf-test-token",))],
        [("input", ("csrf_token",), ("csrf-test-token",))],
        [("input", ("csrf_token",), ("csrf-test-token",))],
    ]


def test_scenario_buttons_have_visible_scenario_specific_accessible_names() -> None:
    """Identical button labels make the three fixed run actions ambiguous."""
    forms = _forms(_render_scenarios())

    assert [_visible_button_label(form) for form in forms] == [
        "Run Feedback Success scenario",
        "Run Governance Denied scenario",
        "Run Human Review Pause scenario",
    ]


def test_csrf_token_with_html_metacharacters_is_escaped_and_preserved() -> None:
    """A token must remain a single parsed hidden value, not become markup."""
    token = "csrf&<>'\"-token"
    page = _render_scenarios(token)

    assert token not in page
    assert [
        control.values("value")
        for form in _forms(page)
        for control in _successful_named_controls(form)
    ] == [(token,), (token,), (token,)]


def test_scenarios_page_omits_fixed_config_descriptions_and_prohibited_fields() -> None:
    """Scenario configuration text must not leak into the browser page."""
    page = _render_scenarios()

    for sentinel in (
        "Fix the add function in calculator.py so that add(1, 2) returns 3.",
        "Modify the test file to always pass.",
        "Request human review for a high-impact change.",
        "human review required for high-impact change",
        'name="prompt"',
        'name="path"',
        'name="patch"',
        'name="command"',
        'name="upload"',
        'name="mode"',
        'name="actions"',
        'name="task_description"',
        'name="reason"',
    ):
        assert sentinel not in page


def test_result_page_renders_only_fixed_typed_trace_text() -> None:
    """Raw worker diagnostics or request text must not appear in a result page."""
    trace = ExecutionTraceView.from_events(
        (
            ActionSelectedEvent(action_kind=DemoActionKind.APPLY_PATCH, sequence=0),
            TestCompletedEvent(outcome=RunOutcome.FAILED, sequence=1),
            FeedbackProducedEvent(feedback_code="initial_failure", sequence=2),
            PolicyDecisionEvent(
                decision=PolicyOutcome.DENY,
                reason_code=PolicyReasonCode.TEST_ASSET_PROTECTION,
                sequence=3,
            ),
            TerminalStatusEvent(task_status=TaskStatus.STOPPED, sequence=4),
        )
    )
    forbidden_context = {
        "raw_stdout": "stdout-sentinel: secret model text",
        "raw_stderr": "stderr-sentinel: internal diagnostic",
        "exception": "exception-sentinel: traceback details",
        "absolute_path": "C:\\private\\model-output.txt",
        "raw_model_output": "model-output-sentinel: arbitrary completion",
        "request_human_reason": "reason-sentinel: sensitive human request",
    }

    page = (
        _templates()
        .get_template("result.html")
        .render(
            trace=trace,
            **forbidden_context,
        )
    )

    assert "action selected: apply_patch" in page
    assert "test completed: failed" in page
    assert "feedback produced: initial_failure" in page
    assert "policy decision: deny (test_asset_protection)" in page
    assert "terminal status: stopped" in page
    for sentinel in forbidden_context.values():
        assert sentinel not in page


def test_base_page_declares_csp_and_referrer_contract_without_inline_script() -> None:
    """C2 supplies browser policy metadata; C1 mirrors these values as headers."""
    page = _render_scenarios()

    assert 'http-equiv="Content-Security-Policy"' in page
    assert "default-src 'self'" in page
    assert "frame-ancestors 'none'" in page
    assert 'name="referrer" content="origin"' in page
    assert 'src="/static/app.js"' in page
    assert "<script>" not in page


def test_submit_script_disables_button_marks_busy_and_announces_without_network() -> (
    None
):
    """A submit event must change only local DOM state and never start a network API call."""
    node = shutil.which("node")
    assert node is not None, "Node.js is required to execute the real C2 browser script"
    runner = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const documentListeners = {};
const submitListeners = {};
const attributes = {};
const button = { disabled: false };
const status = { textContent: "" };
const form = {
  addEventListener(type, listener) { submitListeners[type] = listener; },
  dispatchEvent(event) { submitListeners[event.type](event); },
  querySelector(selector) {
    if (selector === 'button[type="submit"]') return button;
    if (selector === "[data-submit-status]") return status;
    throw new Error("unexpected selector: " + selector);
  },
  setAttribute(name, value) { attributes[name] = value; },
};
global.document = {
  addEventListener(type, listener) { documentListeners[type] = listener; },
  querySelectorAll(selector) {
    if (selector === "form[data-run-form]") return [form];
    throw new Error("unexpected selector: " + selector);
  },
};
let networkCalls = 0;
global.fetch = () => { networkCalls += 1; throw new Error("network not allowed"); };
global.XMLHttpRequest = class {
  constructor() { networkCalls += 1; throw new Error("network not allowed"); }
};
eval(source);
documentListeners.DOMContentLoaded();
form.dispatchEvent({ type: "submit" });
console.log(JSON.stringify({
  buttonDisabled: button.disabled,
  ariaBusy: attributes["aria-busy"],
  liveText: status.textContent,
  networkCalls,
}));
"""
    completed = subprocess.run(
        [node, "-e", runner, str(TEMPLATES.parent / "static" / "app.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert json.loads(completed.stdout) == {
        "buttonDisabled": True,
        "ariaBusy": "true",
        "liveText": "Running fixed scenario…",
        "networkCalls": 0,
    }
