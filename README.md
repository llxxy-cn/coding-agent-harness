# Coding Agent Harness

## Overview

Coding Agent Harness is a governed local agent for making bounded changes to trusted Python repositories and validating them with pytest. The project implements its own decision loop: it builds context, requests one model decision, parses a strict Action, applies capability and Policy checks, dispatches a tool, feeds back objective test results, and decides whether to continue, pause, stop, or succeed.

The delivered core does not use LangChain AgentExecutor, AutoGen, CrewAI, LlamaIndex Agent, the OpenAI Agents SDK, or another packaged agent loop. The OpenAI adapter performs one Responses API call; `HarnessCore` owns orchestration.

Version 0.1.0 is the current Release candidate. It includes an offline deterministic demonstration and one real-provider adapter. Implementation candidate `99b615efa15de2bbda7234817b9d46e5e6d7cfb8` passed the `package-build`, `test (3.11)`, and `test (3.12)` jobs in [GitHub Actions run 31180147117](https://github.com/llxxy-cn/coding-agent-harness/actions/runs/31180147117).

Repository: https://github.com/llxxy-cn/coding-agent-harness

Canonical v0.1.0 Release URL: https://github.com/llxxy-cn/coding-agent-harness/releases/tag/v0.1.0

The GitHub Release page is the authoritative source for current Tag, hosted Release, and asset availability. This document does not claim that Tag creation, hosted Release creation, or asset upload has occurred before GitHub reports it there.

## Features

- Project-owned `LLM → Action → Policy → Tool → Feedback` loop with explicit budgets and stop conditions.
- Nine closed, strict, frozen Action schemas with stable protocol errors.
- Bounded file listing, reading, literal search, read-only Git diagnostics, strict Patch preparation/application, and governed pytest execution.
- Isolated detached Git worktrees under the harness data root; the source repository is not patched.
- SQLite task/session persistence and content-addressed sanitized artifacts.
- Deterministic Policy precedence (`deny → require approval → allow`) plus Approval and Trust bindings.
- Bounded, redacted pytest capture; reliable parsed feedback and state fingerprints.
- Offline `ScriptedMockLLM` repair and safety demonstrations without credentials or network access.
- One real OpenAI provider adapter using the frozen model and fixed release limits.
- Typer CLI with `run`, `status`, `resume`, and the `key` lifecycle commands.

## Installation

Python 3.11 or 3.12 is required.

From a source checkout on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\coding-agent-harness.exe --help
```

Build and install the wheel locally:

```powershell
.\.venv\Scripts\python.exe -m build --no-isolation
py -3.12 -m venv .verify-venv
.\.verify-venv\Scripts\python.exe -m pip install dist\coding_agent_harness-0.1.0-py3-none-any.whl
.\.verify-venv\Scripts\coding-agent-harness.exe --help
```

Delete `.verify-venv` after verification. Installation from a package registry is not claimed.

## Configuration

Configuration resolves in this order:

1. immutable built-in safety defaults;
2. an optional per-user `config.toml` in the platformdirs `coding-agent-harness` user configuration directory;
3. an optional repository `.coding-harness.toml` read from the frozen base commit.

On Windows, the user file is `%LOCALAPPDATA%\coding-agent-harness\config.toml`. Other platforms use the location returned by `platformdirs.user_config_path("coding-agent-harness")`.

Real mode requires the user layer to replace the built-in non-operational model value:

```toml
[llm]
model = "YOUR_APPROVED_OPENAI_MODEL"
```

The repository layer cannot choose a provider or model. It may reduce numeric limits, add protected or sensitive paths, and narrow diagnostic and memory allowlists; attempts to broaden authority are rejected. Unknown fields, interpolation, dynamic evaluation, and environment overrides are rejected.

## Credentials

The sole public command group is `key`:

```text
coding-agent-harness key set
coding-agent-harness key status
coding-agent-harness key update
coding-agent-harness key clear
```

`set` and `update` prompt without echo and store the value in the operating-system keyring. `status` prints only `configured` or `not configured`; `clear` never prints the previous value. There is no plaintext CLI option, environment-variable fallback, `.env` fallback, or configuration-file credential field. Demo mode does not construct the keyring or OpenAI client.

## CLI

Display the command tree:

```text
coding-agent-harness --help
coding-agent-harness key --help
coding-agent-harness run --help
coding-agent-harness status --help
coding-agent-harness resume --help
```

Start real mode after configuring the model and key:

```text
coding-agent-harness run REPOSITORY_PATH "TASK_DESCRIPTION" --trust-repo
```

Start the offline demonstration:

```text
coding-agent-harness run REPOSITORY_PATH "repair calculator addition" --demo --trust-repo
```

Read or resume a persisted task using the canonical UUIDv4 printed by `run`:

```text
coding-agent-harness status TASK_ID
coding-agent-harness resume TASK_ID
```

`--trust-repo` is an explicit assertion that the repository is trusted for the documented local processing and, in real mode, the bounded data sent to the configured provider. It does not disable preflight, worktree isolation, Policy, Approval, Trust binding, or workspace-drift checks.

CLI output is intentionally small: canonical task ID, task status, and a safe summary. It does not print raw pytest output, credential material, internal database paths, or governed-worktree paths.

## Offline Demo

The repeatable source-checkout demonstration copies `tests/fixtures/e2e/repairable_project` to a temporary directory, initializes a clean local Git repository, proves its baseline test fails, and runs the CLI in demo mode. The scripted model reads the defect, proposes a small production-source Patch, passes Policy, applies the Patch in an isolated worktree, runs full pytest, and reaches `succeeded`.

The original fixture and copied source repository remain unchanged; only the generated worktree contains the repair. See [docs/DEMO.md](docs/DEMO.md) for exact commands and safety scenarios.

## Architecture

The dependency direction is `CLI/composition → application/core/ports → injected adapters`. Core and application code do not import SQLite, OpenAI, keyring, Typer, process, or concrete adapter packages. The provider performs one generation; `HarnessCore` owns the loop.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component and data-flow diagrams.

## Security Boundaries

- All supported process launches use argv elements with `shell=False`, fixed working directories, environment allowlists, timeouts, bounded stdout/stderr, and process-tree termination.
- Repository preflight requires a clean Git repository and freezes the base commit before creating a unique detached worktree below the harness data root.
- Path validation rejects escapes, sensitive paths, unsafe symlink components, binary Patch content, and unsupported shell behavior.
- Patch governance runs `prepare → Policy → apply`; deny and approval outcomes have zero Patch side effects. Every allowed Patch forces a full pytest run.
- stdout and stderr are bounded during capture. Sanitized output and reliable parsed results may become verified artifacts; raw pytest output is never persisted.
- Context contains bounded safe summaries, not raw output, credential values, unrestricted history, or arbitrary artifact bytes.
- Unknown test outcomes and workspace drift are not retried as success; they pause for human handling.
- Credential plaintext crosses only the private keyring-to-SDK-constructor boundary. CLI, Application, Core, SQLite, Context, artifacts, and user-visible errors never receive it.

Trusted local code can still consume machine resources or contain behavior outside pytest. Use only repositories you understand, review generated diffs, and keep independent backups.

## Project Layout

```text
src/coding_agent_harness/
  adapters/       concrete filesystem, Git, process, SQLite, artifact, credential, and LLM edges
  application/    task orchestration and persistent session boundary
  cli/            Typer commands and safe rendering
  config/         strict layered configuration and capability resolution
  core/           project-owned loop, context, budgets, state transitions, and Patch Policy mapping
  domain/         frozen Actions, statuses, results, and identifiers
  feedback/       pytest parsing, normalization, fingerprints, and decisions
  patching/       pure Patch preparation and guarded application
  ports/          infrastructure protocols
  security/       Policy, Trust, Approval, canonicalization, redaction, and path controls
tests/            unit, contract, integration, E2E, and inert source fixtures
docs/             assignment source, architecture, and demonstration guidance
```

## Distribution

The supported local artifact is a universal Python wheel plus source distribution:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build --no-isolation
```

The console entry point is `coding-agent-harness = coding_agent_harness.cli.app:main`. Release contents and local evidence are summarized in [RELEASE_NOTES.md](RELEASE_NOTES.md). The canonical `v0.1.0` GitHub Release page is the authoritative source for whether the audited wheel and sdist are currently available.

## License

Coding Agent Harness is released under the MIT License.

Copyright (c) 2026 llxxy-cn

See [LICENSE](LICENSE) for the standard terms. Third-party dependencies are not relicensed by this project and remain subject to each upstream license. The principal runtime dependencies use their upstream licenses: Pydantic, Typer, FastAPI, keyring, and platformdirs use MIT terms; Uvicorn, Jinja2, and HTTPX use BSD-family terms; the OpenAI Python library uses Apache-2.0 terms. Consult each installed distribution's metadata and upstream repository for the authoritative text and notices.

## Known Limitations

- Governed repair is limited to Python repositories using pytest.
- Only one real provider, OpenAI, is implemented.
- Worktrees are not deleted automatically; inspect and remove them manually only after preserving needed evidence.
- Real mode depends on a configured local system keyring, an approved OpenAI model, network availability, and provider account access.
- Memory is bounded current-task history, not long-term cross-project retrieval.
- There is no parallel task execution or multi-agent coordination.
- Process controls are bounded local execution, not a production-grade OS sandbox.
- Two symlink-security tests may skip on Windows when the account lacks symlink privilege.
- Tag creation, hosted Release creation, and asset upload remain separately authorized publication actions until they are reflected on the canonical GitHub Release page.
