# Release Notes

## v0.1.0

Repository:
https://github.com/llxxy-cn/coding-agent-harness

Tag: `v0.1.0`

Canonical v0.1.0 Release URL:
https://github.com/llxxy-cn/coding-agent-harness/releases/tag/v0.1.0

The GitHub Release page is the authoritative source for current Tag, hosted Release, and asset availability. These notes do not claim that Tag creation, hosted Release creation, or asset upload has occurred before GitHub reports it there.

### Implemented

- Self-implemented bounded Agent loop with strict Action parsing, typed dispatch, feedback reinjection, budgets, and deterministic stopping.
- Bounded filesystem, read-only Git, diagnostic, strict Patch, and pytest adapters.
- Code-based Policy, exact Trust/Approval bindings, isolated worktrees, SQLite state, and verified sanitized artifacts.
- Pytest parsing, stable fingerprints, progress/regression/no-progress/loop decisions, and bounded safe Context.
- Deterministic `ScriptedMockLLM` plus one real OpenAI Responses adapter.
- System-keyring credential lifecycle through `coding-agent-harness key`.
- CLI `run`, `status`, and `resume`, including a fully offline repair demonstration.
- Universal Python wheel and source-distribution build configuration for Python `>=3.11,<3.13`.

### Verification Evidence

- Implementation candidate `99b615efa15de2bbda7234817b9d46e5e6d7cfb8` passed the `package-build`, `test (3.11)`, and `test (3.12)` jobs in [GitHub Actions run 31180147117](https://github.com/llxxy-cn/coding-agent-harness/actions/runs/31180147117).
- Full repository before the final delivery-contract additions: 371 passed, 2 skipped, 0 warnings.
- Milestone C offline E2E: 8 passed, including real local Git worktree, Patch, and pytest execution.
- Contract suite before this documentation milestone: 11 passed.
- The two skips are Windows symlink-security tests when the running account lacks symlink privilege.
- Build artifact and isolated-install evidence is recorded during Milestone D verification and must be refreshed before publication.

### Distribution Artifacts

Verified local artifact names:

- `coding_agent_harness-0.1.0-py3-none-any.whl`
- `coding-agent-harness-0.1.0.tar.gz`

Install the wheel with `python -m pip install coding_agent_harness-0.1.0-py3-none-any.whl`. The installed CLI exposes `run`, `status`, `resume`, and `key`. The fully offline `run --demo` path exercises the isolated-worktree repair loop without a provider credential.

This project is not published to a package registry. Current Tag, hosted Release, and asset availability is reported by the canonical GitHub Release page.

### Known Limitations

- Python/pytest repositories only.
- One real provider: OpenAI.
- No automatic worktree cleanup.
- No parallel task scheduling, cross-project long-term memory, or cross-language test framework support.
- Local process controls are not a production-grade OS sandbox.
- Real-provider operation requires local keyring configuration, an approved model, network access, and provider account access; these are not exercised by offline tests.
- Tag creation, hosted Release creation, and asset upload remain human-owned delivery gates until they are actually executed.
