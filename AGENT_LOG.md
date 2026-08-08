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

---

## RETROSPECTIVE RECONSTRUCTION — not a contemporaneous record (2026-08-08)

> The following entries were reconstructed on 2026-08-08 from git commit history and codebase audit. They are not contemporaneous logs. Subagent IDs, reviewer IDs, exact timestamps, prompts, and human approval details for Tasks 1–17 are not retained. Each group explicitly lists which Task numbers it covers. Task status was determined by checking each Task's original acceptance criteria against the actual codebase — not by assuming completion from Milestone membership alone.

### Retrospective Group: Tasks 1–2

- **Covers Tasks:** 1, 2
- **Git-provable commit date:** 2026-08-06
- **Commits:** `f976cc271c02b50933ee90dae28ac69bdeedb4f0` (Task 1), `634712f0e84d6883304c11cc89df327359bca394` (Task 2)
- **Subagent ID:** not retained
- **Reviewer ID:** not retained
- **Exact timestamp:** not recorded
- **Task 1 status:** COMPLETED — package skeleton and test gate
- **Task 2 status:** COMPLETED — domain models and strict action schema

### Retrospective Group: Tasks 3–9

- **Covers Tasks:** 3, 4, 5, 6, 7, 8, 9
- **Git-provable commit date:** 2026-08-06
- **Commits:** `fc12c5989b71975b280bdaa3d5ac6f6e7f70215c` (Task 3), `d176198feebe9e405b2a06fa479c47ee2a0a2694` (Task 4), `10455b31ce60f18d1450aa42fb88393a79c785fc` (Task 5), `55b6186a3dfa6c95287b8b92d6f0c49d0d14e98d` (Task 6), `ab5c23fc1cb58ddde32920e463b83413741b9270` (Task 7), `5de2d27dfb70ac606201b07a4c867aa8d4006549` (Task 8), `cd431e2a7482db28955f79a768c7b79d0aefc473` (Task 9)
- **Subagent ID:** not retained
- **Reviewer ID:** not retained
- **Exact timestamp:** not recorded
- **Task 3 status:** COMPLETED — core port contracts
- **Task 4 status:** COMPLETED — frozen configuration and capabilities
- **Task 5 status:** COMPLETED — persistent state and secure artifacts
- **Task 6 status:** COMPLETED — guarded filesystem and typed tools
- **Task 7 status:** COMPLETED — strict patch transactions
- **Task 8 status:** COMPLETED — canonical policy and trust bindings
- **Task 9 status:** COMPLETED — bounded pytest execution

### Retrospective Group: Milestone A / Tasks 10, 12, 13

- **Covers Tasks:** 10, 12, 13
- **Git-provable commit date:** 2026-08-06
- **Commit:** `630ba9c02315b534addc0aa3a4a011815c9b7271`
- **Subagent ID:** not retained
- **Reviewer ID:** not retained
- **Exact timestamp:** not recorded
- **Task 10 status:** COMPLETED AS PART OF MILESTONE A — core feedback functionality (`feedback/pytest_parser.py`, `normalize.py`, `fingerprint.py`, `engine.py`, `output.py`) exists and passes tests; planned filename absent: `test_normalize.py`, `tests/fixtures/pytest_outputs/` fixtures; equivalent evidence: `test_pytest_parser.py` covers pass/failure/collection_error/unparseable/truncated/environment_error, `test_engine.py` covers all FeedbackKind + fingerprint; remaining limitation: ANSI/path/time/temp-dir normalization not individually tested
- **Task 12 status:** COMPLETED AS PART OF MILESTONE A — core memory/context functionality (`core/memory.py`, `core/context.py`) exists and passes tests; planned filename absent: `test_memory.py`, `tests/integration/sqlite/test_memory_repository.py`; equivalent evidence: `test_context.py` covers ContextBuilder determinism, redaction, bounded output; remaining limitation: memory persistence not individually tested
- **Task 13 status:** COMPLETED AS PART OF MILESTONE A — ScriptedMockLLM, HarnessCore, budget, state machine exist and pass tests; planned filename absent: `test_budget.py`, `test_state_machine.py`; equivalent evidence: `test_harness.py` covers complete loop including budget limits and state transitions, `test_scripted_mock.py` covers Mock behavior; remaining limitation: budget and state machine not individually unit-tested

### Retrospective Group: Milestone B / Tasks 11, 15, 16

- **Covers Tasks:** 11, 15, 16
- **Git-provable commit date:** 2026-08-06
- **Commit:** `7eff8038bdc7f15df8a3bcdfb215d93cb71ee6d8`
- **Subagent ID:** not retained
- **Reviewer ID:** not retained
- **Exact timestamp:** not recorded
- **Task 11 status:** PARTIAL — worktree and preflight exist (`adapters/git/worktree.py`, `adapters/git/readonly.py`, `application/preflight.py`); missing: `application/recovery.py`, `adapters/locking/file_lease.py`, `tests/integration/git/`, `tests/integration/locking/`
- **Task 15 status:** COMPLETED AS PART OF MILESTONE B — OpenAI adapter and credential store exist, contract tests pass; planned filename absent: `adapters/credentials/fake_store.py`, `tests/unit/security/test_outbound_context.py`; equivalent evidence: `test_credential_store.py` has own `FakeKeyringBackend`, `test_openai_client.py` covers single generation/redaction/no-retry, `test_context.py` covers redaction; remaining limitation: outbound context trust manifest not individually tested at OpenAI mock boundary
- **Task 16 status:** PARTIAL — CLI complete (`cli/app.py`); WebUI explicitly deferred (no `web/` directory in `src/`)

### Retrospective Group: Milestone C / Tasks 14, 17

- **Covers Tasks:** 14, 17
- **Git-provable commit date:** 2026-08-06
- **Commit:** `8aae4f6f962d877a9860de7412589fc55ff92e19`
- **Subagent ID:** not retained
- **Reviewer ID:** not retained
- **Exact timestamp:** not recorded
- **Task 14 status:** COMPLETED AS PART OF MILESTONE C — main chain runs E2E with real pytest (`application/service.py`, `application/session_store.py`; e2e tests pass); planned filename absent: `application/baseline.py`, `application/approvals.py`, `application/reporting.py`, `test_regression_rollback.py`, `test_approval_resume.py`, `test_real_pytest_chain.py`; equivalent evidence: baseline/approvals/reporting covered by `composition.py` and `service.py`, `test_cli_repair_demo.py` covers real pytest E2E, `test_cli_safety_scenarios.py` covers approval/resume; remaining limitation: regression rollback (Red step, not Completion criterion) not tested
- **Task 17 status:** PARTIAL — mechanism demonstrations exist as e2e tests (`test_cli_repair_demo.py`, `test_cli_safety_scenarios.py`, `test_mock_feedback_action_change.py`); missing: `src/coding_agent_harness/demo/` module, `demo_repos/` directory, `scripts/run_mechanism_demo.py`

### Retrospective Group: Milestone D / Tasks 18–20

- **Covers Tasks:** 18, 19, 20
- **Git-provable commit dates:** 2026-08-06 to 2026-08-07
- **Commits:** `105b9c9b44230769dd8aaec675fabc30aad14cd3` (Task 18/19), `2fd76efb0d43a337530315b6f42f6a138aaafc57` (REFLECTION.md), `8b66fe2e5bcc1bcfc9bffabb4f7d4bf2c5d21d00` (SQLite schema in distributions), `99b615efa15de2bbda7234817b9d46e5e6d7cfb8` (CI build backend), `3e7b312d5ce04f7bcfd1cc180d3010c0d1b13d95` (release delivery status)
- **Subagent ID:** not retained
- **Reviewer ID:** not retained
- **Exact timestamp:** not recorded
- **Task 18 status:** PARTIAL — package build and CI definitions pass (`.gitlab-ci.yml`, `.github/workflows/ci.yml`; 9 delivery tests pass; CI passed 6 checks on PR #1); missing: `Dockerfile`, `.dockerignore`
- **Task 19 status:** PARTIAL — documentation, license, and reflection exist (`README.md`, `LICENSE`, `REFLECTION.md`, `SPEC_PROCESS.md`, `AGENT_LOG.md`; 9 delivery tests pass); `scripts/check_course_delivery.py --preflight` not implemented — cannot prove "distinguish AI-owned artifacts from pending student-owned Reflection and report" completion criterion
- **Task 20 status:** PARTIAL — tag `v0.1.0` at `3e7b312`, Release created, assets uploaded, Reflection committed, CI passed, local tests and package build completed; image build, release manifest, `verify_release.py`, public demo deployment, and deployed scenario verification not completed; hosted GitHub Release URL exists, but no public application/demo deployment URL is recorded

---

## 2026-08-08 — PR #1 Merge and CI

- Task: A.6 feedback-driven action-change follow-up / branch completion
- Skills: finishing-a-development-branch, verification-before-completion
- Prompt/context summary: evaluate four branch-finishing options after PR CI passed; preserve original task commit and evidence chain
- Subagent/output evidence: reference implementation/reviewer IDs already recorded in the preceding A.6 entry; task commit `9be61dff3a15acdeb2899aea76ee9dd98b3efd4f`
- Human intervention: human selected "Create a merge commit", confirmed merge in GitHub, deleted remote task branch, and authorized local worktree/local branch cleanup
- Verification: six PR checks passed and post-merge main CI run 31249036771 passed
- PR #1: `task/a6-feedback-action-change` → `main`, merged via "Create a merge commit"
- Task commit: `9be61dff3a15acdeb2899aea76ee9dd98b3efd4f`
- Merge commit: `95c007806f232183677d1775535220fd122e67cd`
- CI run URL: `https://github.com/llxxy-cn/coding-agent-harness/actions/runs/31249036771`
- CI result: 6 checks passed
- Post-merge cleanup: sibling worktree removed, local task branch deleted, `feature/webui-v0.2.0` fast-forwarded to `main`
- Lesson: merge commit preserved the original task commit body, subagent/reviewer identifiers, human changes, and PR history
- Exact timestamp: not recorded

## 2026-08-08 — Evidence Reinforcement Task

- Task: process-evidence reinforcement for PLAN.md, AGENT_LOG.md, SPEC_PROCESS.md
- Skills: using-git-worktrees, writing-plans, subagent-driven-development, requesting-code-review, verification-before-completion
- Prompt/context summary: append-only retrospective reconstruction; no historical fabrication; Task 1–20 statuses checked against acceptance criteria; only three documentation files allowed
- Branch: `task/evidence-reinforcement` (from `main` @ `95c0078`)
- Worktree: sibling worktree (no machine-local path recorded)
- Scope: add retrospective evidence to `PLAN.md`, `AGENT_LOG.md`, `SPEC_PROCESS.md`
- Implementation subagent: `ses_01f37d383ffe8kko1KCg4hgF3o`
- Correction subagents:
  - `ses_01f0f9f3fffe2Yp5ilYj6PtSUS`
  - `ses_01f08ce93ffeZkUyTi11rndjwx`
  - Task 19/20/A.6 correction IDs: not retained
- Final Stage 1 reviewer: `ses_01e2bb27fffeMIy91TgvTJ25cn` — PASS
- Final Stage 2 reviewer: `ses_01e27e318ffetpDStS10kNx3pY` — APPROVED
- Human intervention:
  - required cold-start gate status NOT RECORDED;
  - rejected inferred approval/bypass;
  - required complete unified-diff review;
  - corrected A.6 chain by removing nonexistent baseline fail;
  - changed Tasks 19 and 20 to PARTIAL;
  - distinguished hosted Release URL from public application deployment;
  - required retry after an empty Stage 1 review.
- Tests: delivery 9 passed; full 377 passed, 2 skipped; git diff --check clean
- Status at the time of this entry: awaiting human review; no commit, no push, no PR
- Lesson: later implementation is not evidence that a historical gate passed; a missing reviewer response cannot be replaced by controller self-review; completion status must follow acceptance evidence rather than milestone membership
- Exact timestamp: not recorded
