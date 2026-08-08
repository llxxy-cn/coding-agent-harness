# Agent Log

## 2026-08-06 — Day 3, Tasks 1–2

- Branch: `feature/day3-domain-foundation`
- Base commit: `daffeb6857e10101d92091c8dcb6e60e8772aea6`
- Skills: using-superpowers, brainstorming, executing-plans, test-driven-development, verification-before-completion
- Scope: Task 1 package skeleton followed by Task 2 frozen domain contracts; no ports, configuration, Mock LLM, or main loop
- Environment: repository-local Python 3.12 virtual environment; all Python commands use `.\.venv\Scripts\python.exe`
- Task 1 Red: package collection failed because `coding_agent_harness` did not exist; repository hygiene test failed because `.gitignore` did not exist

## 2026-08-06 — Course Submission Core Delivery Path

- Assistant tooling: Codex with Superpowers supported requirements clarification, planning, TDD, focused review, and evidence-based verification.
- Human ownership: the student confirmed frozen contracts, permission boundaries, approved file scopes, exact commits, and every transition between integration milestones. External publication remains subject to separate human review and authorization.
- Representative prompt types: authoritative contract extraction, narrow Red scenarios, minimum Green implementation, security-boundary review, exact staging, and release verification.
- Workflow: Red → Green → verification. New behavior was introduced behind deterministic tests, followed by focused, contract, full-suite, diff, and static checks appropriate to each milestone.
- Review record: generated code and documentation are treated as reviewable drafts until tests pass and the human reviewer accepts the relevant milestone. No command output or human action is invented in this log.
- Safety record: the log excludes credential values, private data, raw model responses, raw test output, and machine-specific full paths. Offline tests use ScriptedMockLLM and temporary repositories; real provider calls are not used for verification.
- Key lesson: strict domain boundaries exposed adapter mismatches early, while end-to-end tests found integration defects that unit tests could not reveal. Release claims must distinguish locally observed evidence from publication, CI, and deployment evidence.
- Milestone D local evidence: documentation contracts passed 4 tests and the expanded repository suite passed 371 tests with the two existing Windows privilege skips and no warnings. The first offline package build stopped before artifact creation because the active venv lacked the reviewed setuptools build backend; an explicit no-index lookup found no compatible cached distribution, and no network fallback was used.
- Release-candidate follow-up: after the approved build backend was installed from standard PyPI, wheel and source distribution builds completed and the wheel passed an isolated Python 3.12 installation check. The selected license is MIT, with copyright held by llxxy-cn.
- Delivery endpoints: the repository is planned at `https://github.com/llxxy-cn/coding-agent-harness`; Tag `v0.1.0` and the hosted Release at `https://github.com/llxxy-cn/coding-agent-harness/releases/tag/v0.1.0` are planned and have not been created.
- Automation boundary: GitHub and GitLab CI definitions are prepared and locally contract-tested. No remote CI run is claimed; remote execution remains pending until the student configures and publishes the repository.
- Student-owned gate: `REFLECTION.md` remains entirely student-authored and is not created or drafted by the agent.

## 2026-08-07 — Subsequent Delivery Checkpoint

- The repository push is complete, and the student-authored `REFLECTION.md` has been committed.
- Implementation candidate `99b615efa15de2bbda7234817b9d46e5e6d7cfb8` passed the `package-build`, `test (3.11)`, and `test (3.12)` jobs in `https://github.com/llxxy-cn/coding-agent-harness/actions/runs/31180147117`.
- Earlier pending statements above record the state at that earlier checkpoint and are retained as historical evidence.
- Tag creation, hosted Release creation, and asset upload are not claimed as complete before they are actually executed.

## 2026-08-08 13:57 +08:00 — A.6 Feedback-Driven Action Change Evidence

- Task: A.6 feedback-driven action change demonstration
- Branch: `task/a6-feedback-action-change` (from `feature/webui-v0.2.0`, commit `3e7b312`)
- Worktree: sibling worktree `../coding-agent-harness-a6-feedback` (no `.gitignore` change needed)
- Skills triggered: using-git-worktrees, writing-plans, subagent-driven-development, test-driven-development, requesting-code-review, verification-before-completion
- Scope: create one e2e evidence test proving feedback-driven action change through HarnessCore with ScriptedMockLLM; update DEMO.md; no production file changes, no commit, no push, no PR
- Fresh implementation subagent: task id `ses_020268b03ffeOKjUFRi4C7LIYb`; created `tests/e2e/test_mock_feedback_action_change.py` and appended `docs/DEMO.md`; test passed on first run (characterization/evidence pass, not Red)
- Stage 1 review (spec/assignment compliance): task id `ses_0201fbfeaffe4gB7JPU7iAt1Vq`; verdict PASS; all 11 requirements MET; no issues found
- Stage 2 review (code quality): task id `ses_020191f76ffe32ibddmdDmIkMP`; verdict APPROVED; no issues at any severity
- Files modified: `tests/e2e/test_mock_feedback_action_change.py` (new, 92 lines), `docs/DEMO.md` (appended 12 lines)
- Test results: focused 1 passed; related (harness + feedback) 18 passed; contract 11 passed; full suite 377 passed, 2 skipped (pre-existing Windows privilege skips); `git diff --check` clean
- Human intervention: Human review required removal of the machine-local absolute path, normalization of the demo heading, and use of a platform-neutral pytest command. Awaiting commit, push, and PR approval.
- Lesson: the `_SequentialPatchPreparer` was necessary because Patch B uses Patch A's result as its pre-image (`-return 1` → `+return 2`), and the `DefaultPatchPreparer`'s fixed snapshot (`return 0`) would cause a `ValueError("context mismatch")` in `prepare()`. The real `prepare()` function's context validation implicitly enforces correct patch ordering — if actions arrived out of order, the test would fail at preparation time, not at assertion time. This is stronger than a mock-sequencing assertion because it validates the semantic contract between patches.
