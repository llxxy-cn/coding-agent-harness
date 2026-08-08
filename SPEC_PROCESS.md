# Specification and Delivery Process

## Scope and Evidence Rules

This document summarizes the observed specification, planning, implementation, and release-candidate process for Coding Agent Harness. It records repository evidence and reviewed decisions rather than reproducing private chat transcripts. It does not contain credentials, raw model output, raw pytest output, private filesystem paths, or unobserved remote results.

The student owns product decisions and final acceptance. Codex and Superpowers supported question framing, plan decomposition, TDD, review, and verification. Every external state change—expanded filesystem access, staging, commit, network use, and publication—required a separately confirmed scope.

## Specification to Plan

The course assignment was first translated into `SPEC.md`, with explicit requirements for a project-owned Agent loop, typed Actions, deterministic feedback, code-enforced governance, bounded memory/context, credential handling, and distribution. `PLAN.md` then decomposed those contracts into atomic Tasks with named interfaces, Red commands, minimum Green behavior, dependency edges, and completion evidence.

A cold-start review used only SPEC and PLAN context to expose implicit assumptions. The reviewed baseline was committed as:

- `daffeb6857e10101d92091c8dcb6e60e8772aea6` — refined cold-start and domain contracts.

The current release later grouped remaining atomic Tasks into four integration milestones without deleting their detailed traceability. This retained the contract source while making the vertical delivery sequence explicit.

## Three Key Iterations

### Iteration 1 — Strict domain and port boundaries

Initial Red tests established that the package and domain contracts did not yet exist. Green introduced the package gate, frozen Pydantic models, closed enums, strict Action parsing, and narrow ports. Human review repeatedly rejected implicit coercion, guessed fields, arbitrary shell input, and infrastructure imports in Core.

Evidence:

- `f976cc2` — package skeleton and test gate.
- `634712f` — frozen domain models and strict Action schema.
- `fc12c5989b71975b280bdaa3d5ac6f6e7f70215c` — core port contracts.
- `d176198` — frozen configuration and capabilities.

Result: downstream work received strict values and protocols instead of unbounded dictionaries or provider-specific objects.

### Iteration 2 — State, tools, Patch, Policy, and test execution

Focused Red tests drove SQLite state and artifacts, bounded filesystem/Git/process tools, pure Patch preparation, transactional apply/compensation, Policy precedence, exact Trust/Approval binding, and sanitized pytest execution. Review corrected approval field names, Policy threshold expectations, and the `FrozenConfig` tuple-to-`FrozenCommand` JSON-array boundary without weakening strict models.

Evidence:

- `10455b31ce60f18d1450aa42fb88393a79c785fc` — persistent state and secure artifacts.
- `55b6186a3dfa6c95287b8b92d6f0c49d0d14e98d` — guarded filesystem and typed tools.
- `ab5c23fc1cb58ddde32920e463b83413741b9270` — strict Patch transactions.
- `5de2d27dfb70ac606201b07a4c867aa8d4006549` — canonical Policy and Trust bindings.
- `cd431e2a7482db28955f79a768c7b79d0aefc473` — bounded pytest execution.

Result: raw test bytes remain transient, Patch writes occur only after prepare and Policy, and deny/approval outcomes have zero Patch side effects.

### Iteration 3 — Agent orchestration, real composition, and E2E repair

The next Red set covered pytest parsing, feedback fingerprints, bounded Context, `ScriptedMockLLM`, stop budgets, and the self-implemented `HarnessCore` loop. A second integration step connected the OpenAI single-generation adapter, system keyring lifecycle, CLI, persistent sessions, preflight, and isolated worktrees. E2E tests then used a temporary local Git repository, real Patch application, and real pytest to expose production wiring defects that unit fakes could not reveal.

Evidence:

- `630ba9c02315b534addc0aa3a4a011815c9b7271` — scripted Agent repair loop.
- `7eff8038bdc7f15df8a3bcdfb215d93cb71ee6d8` — real provider and CLI runtime.
- `8aae4f6f962d877a9860de7412589fc55ff92e19` — offline E2E repair and safety workflows.

Result: the offline demonstration proves baseline failure, isolated Patch, full pytest pass, persisted success status, safety rejection, human pause, no-progress stop, and recovery eligibility without a network or real provider.

## TDD and Verification Workflow

The repeated workflow was:

1. Write focused tests for the reviewed contract.
2. Run Red and classify failures as test defects or missing production behavior.
3. Repair mechanical test defects without changing assertions.
4. Implement the minimum Green within an explicit file whitelist.
5. Run focused tests, then contract and full suites when authorized.
6. Run `git diff --check`, status inspection, dependency-boundary scans, credential scans, and archive inspection.
7. Stage only an exact reviewed file list and commit only after a human gate.

Release-candidate evidence observed locally:

- `371 passed, 2 skipped, 0 warnings`.
- wheel and sdist build completed for version 0.1.0.
- Python 3.12 isolated installation succeeded from the built wheel.
- isolated package metadata, import path, console entry point, and five CLI help commands were verified.
- the two skips are the existing Windows symlink-privilege cases.

## Human Review and Permission Boundaries

The student supplied exact scopes for each Task and integration milestone, corrected test expectations where the production contract was already right, selected the MIT License and copyright holder, and confirmed the repository and planned release identifiers. The assistant did not configure a remote, publish artifacts, create a Tag, or create a hosted release.

On Windows, some ordinary `apply_patch` or deletion operations were blocked by the execution sandbox. Temporary expanded access was authorized only for named files or a previously listed reproducible cache/build directory. Each such operation stopped at the authorized boundary; recursive deletion targets were resolved inside the repository or system TEMP before removal.

## Accepted and Rejected Suggestions

Accepted decisions included strict frozen schemas, code-based Policy/feedback, adapter injection, worktree isolation, bounded output, system-keyring credentials, an offline scripted demonstration, and layered milestones. These choices were retained because they remain deterministic when the real LLM is removed.

Rejected or deferred suggestions included a packaged Agent runner, arbitrary shell execution, environment credential fallback, a second provider, parallel tasks, cross-project memory, and unverified publication claims. They either violated the course mechanism boundary, expanded authority, or lacked current evidence.

## Critical Reflection on the Process

The strongest part of the Superpowers workflow was the separation of contract review, Red evidence, minimum Green, and fresh verification. It made model coercion, Policy precedence, workspace drift, and adapter wiring observable. The main process cost was that mechanical fixture issues sometimes obscured the intended Red; explicitly classifying test defects before Green prevented those errors from weakening production contracts.

The milestone layer improved delivery visibility, but it did not erase the atomic Tasks. That distinction matters: a runnable vertical loop is evidence for integration, while remote CI, student reflection, and publication require their own observed gates.

## Pending External and Student-Owned Evidence

- remote CI: pending verification
- hosted release: planned, not created
- Git remote, push, Tag, and Release assets: not performed
- `REFLECTION.md`: student-authored and not created or edited by the assistant

The planned repository is `https://github.com/llxxy-cn/coding-agent-harness`. The planned `v0.1.0` release address is `https://github.com/llxxy-cn/coding-agent-harness/releases/tag/v0.1.0`. These addresses are identifiers for the next human-authorized stage, not evidence that remote CI or the hosted release exists.

### Subsequent Delivery Checkpoint — 2026-08-07

The repository has been pushed, and the student-authored `REFLECTION.md` has been committed. Implementation candidate `99b615efa15de2bbda7234817b9d46e5e6d7cfb8` passed the `package-build`, `test (3.11)`, and `test (3.12)` jobs in `https://github.com/llxxy-cn/coding-agent-harness/actions/runs/31180147117`. The pending statements immediately above remain as historical evidence of the earlier checkpoint. Tag creation, hosted Release creation, and asset publication are not claimed as complete before they are actually executed.

---

## Cold-Start Validation Evidence Supplement

> **RETROSPECTIVE RECONSTRUCTION — not a contemporaneous record (2026-08-08):** This supplement records cold-start validation evidence observed during a 2026-08-08 read-only audit.

- Cold-start sibling worktrees exist on `cold-start/*` branches at commit `acc003c`.
- One worktree contains untracked Task 1/2 files — "observed during 2026-08-08 read-only audit, not preserved as committed evidence."
- Gate status: **NOT RECORDED** — `PLAN.md` retained "NOT PASSED", implementation proceeded (from `f976cc2` onward), but no record of formal gate passage exists. Later implementation commits are evidence that work proceeded, not evidence that the gate formally passed.
- No verbal approval is inferred and the gate is not characterized as intentionally bypassed.

## PR #1 Merge Evidence

- Task commit: `9be61dff3a15acdeb2899aea76ee9dd98b3efd4f`
- Merge commit: `95c007806f232183677d1775535220fd122e67cd`
- CI run URL: `https://github.com/llxxy-cn/coding-agent-harness/actions/runs/31249036771`
- CI result: 6 checks passed
- Post-merge: local `main` fast-forwarded to `95c0078`, `feature/webui-v0.2.0` fast-forwarded to `main`, `v0.1.0` tag unchanged at `3e7b312`

## A.6 Evidence Task Record

- Test file: `tests/e2e/test_mock_feedback_action_change.py`
- Behavior chain: Patch A (`return 0` → `return 1`) → full test FAILED → sanitized feedback "failed" enters the second LLM context → Patch B (`return 1` → `return 2`) → full test PASSED → TaskStatus.SUCCEEDED
- Result: characterization/evidence pass (not Red)
- Subagent task ID: `ses_020268b03ffeOKjUFRi4C7LIYb`
- Stage 1 reviewer: `ses_0201fbfeaffe4gB7JPU7iAt1Vq` (PASS)
- Stage 2 reviewer: `ses_020191f76ffe32ibddmdDmIkMP` (APPROVED)

## Test Count Update Note

> **RETROSPECTIVE RECONSTRUCTION — not a contemporaneous record (2026-08-08):** As of 2026-08-08, the full test suite count is 377 passed, 2 skipped (after adding the A.6 evidence test). The earlier "371 passed, 2 skipped, 0 warnings" record above remains as historical evidence of the earlier checkpoint and is not removed.

## Retrospective Status Update

> **RETROSPECTIVE RECONSTRUCTION — not a contemporaneous record (2026-08-08):** The earlier "remote CI: pending verification" and "hosted release: planned, not created" statements above are historical records from an earlier checkpoint. As of 2026-08-08, remote CI has passed (6 checks in `https://github.com/llxxy-cn/coding-agent-harness/actions/runs/31249036771`) and the hosted release has been created (`v0.1.0` at `https://github.com/llxxy-cn/coding-agent-harness/releases/tag/v0.1.0`). The old statements are retained as historical evidence and are not removed.
