# Offline Demonstration

## Purpose

This demonstration proves the project-owned Agent loop, code-based Policy, real Patch application, real local pytest feedback, isolation, persistence, and safe stop behavior without OpenAI, a system keyring, a Git remote, or network access.

Run it from a source checkout with Python 3.11 or 3.12, the project `.venv`, Git, and the project dependencies already installed.

## Prepare a Disposable Repository

The fixture source is inert inside the main test suite. Copy it before use:

```powershell
$demoRoot = Join-Path $env:TEMP "coding-agent-harness-demo"
New-Item -ItemType Directory -Force -Path $demoRoot | Out-Null
Copy-Item -Recurse tests\fixtures\e2e\repairable_project (Join-Path $demoRoot "repository")
Set-Location (Join-Path $demoRoot "repository")
git init
git config user.email "demo@example.invalid"
git config user.name "Offline Demo"
git config core.autocrlf false
git add -- calculator.py pyproject.toml tests/test_calculator.py
git commit -m "fixture baseline"
```

Do not point the demonstration at a repository containing work you need to preserve. The harness refuses a dirty source repository and creates a detached worktree below its data root.

## Prove the Baseline Failure

From the disposable repository:

```powershell
REPOSITORY_CHECKOUT\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Expected evidence includes one failing test because `add(2, 3)` returns `-1` instead of `5`.

## Run the Offline Repair

Return to the Coding Agent Harness checkout, then run:

```powershell
.\.venv\Scripts\coding-agent-harness.exe run DEMO_REPOSITORY "repair calculator addition" --demo --trust-repo
```

Expected key output:

```text
task_id: CANONICAL_UUID_V4
status: succeeded
summary: task succeeded
```

The exact identifier changes per run. The demonstration uses `ScriptedMockLLM`; it does not read a credential or construct an OpenAI client.

## Verify the Result

The copied source repository remains at its frozen commit with no working-tree change. The generated detached worktree contains the production-source repair. Running the current `.venv` Python and full pytest inside that worktree reports one passing test.

The automated proof is:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/e2e/test_cli_repair_demo.py `
  tests/e2e/test_cli_safety_scenarios.py -q
```

`test_offline_cli_demo_repairs_only_isolated_worktree_with_real_pytest` asserts baseline failure, source HEAD/status preservation, Patch isolation, and the repaired full-test pass. `test_new_demo_runtime_reads_persisted_success_status` proves a new runtime can read the same task.

## Policy deny Scenario

Run the focused safety test:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/e2e/test_cli_safety_scenarios.py::test_policy_deny_never_applies_test_asset_patch -q
```

The scripted Action attempts to modify `tests/test_calculator.py`. Policy returns a stable deny outcome, Patch apply is never called, and the test asset remains unchanged.

## invalid Action Scenario

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/e2e/test_cli_safety_scenarios.py::test_invalid_actions_stop_without_tool_or_patch_side_effects -q
```

Invalid JSON and an unknown Action produce safe protocol feedback, consume the configured Action budget, perform no tool/Patch side effects, and stop deterministically.

The same file also demonstrates RequestHuman pause, no-progress stop, unparseable-test pause without raw-output context leakage, and cross-runtime resume eligibility.

## Troubleshooting

- `repository is invalid`: confirm the demo path exists and is a directory.
- `task could not be started`: confirm the copied repository is a clean local Git repository with one commit and pass `--trust-repo`.
- Baseline unexpectedly passes: recreate the disposable copy from the committed fixture.
- Pytest cannot start: use the repository-local `.venv` Python and confirm pytest is installed.
- Worktree reports drift: do not run formatters or tests that write governed files during the harness run; recreate the disposable repository.
- A previous task cannot be found: use the same harness data root and the exact UUIDv4 printed by `run`.

The demo does not contact a remote, fetch dependencies, delete worktrees, or modify the source fixture.

## Feedback-Driven Action Change Scenario

Run the focused mechanism test:

```bash
python -m pytest tests/e2e/test_mock_feedback_action_change.py -q
```

The test uses `ScriptedMockLLM` to drive two distinct `ApplyPatchAction` turns through `HarnessCore`. The first patch changes `return 0` to `return 1`; the forced full test returns FAILED. The sanitized failure summary (`"failed"`) enters the second LLM context as `feedback_summary`. `ScriptedMockLLM` then returns a different `ApplyPatchAction` that changes `return 1` to `return 2` — using Patch A's result as its pre-image. The second full test passes; `FeedbackEngine` returns `PASSED`; the task reaches `SUCCEEDED`.

The test does not call a real Provider, keyring, SQLite database, Git remote, or user repository.

## Web UI v0.2.0 Demo

The Web UI is a fixed, offline, deterministic demonstration. It serves exactly
three scenarios: `feedback_success`, `governance_denied`, and
`human_review_pause`. Their repositories, task descriptions, and scripted
actions are fixed in the package; the browser cannot submit an arbitrary
repository, prompt, or action. Runs use `ScriptedMockLLM`, so the Web UI does
not use a Provider, keyring, or Git remote.

Start it with a canonical HTTPS origin. `--origin` is required and must be an
HTTPS origin; it declares the origin used for request validation and does not
itself create TLS.

```powershell
.\.venv\Scripts\coding-agent-harness.exe web --origin https://demo.example.com --host 127.0.0.1 --port 8000
```

The server always uses one Uvicorn worker. Each run is synchronous, with a
global concurrency limit of one and a 60-second request deadline.

### HTTPS Deployment Boundary

For HTTPS termination at a reverse proxy, bind the application only to a
loopback or private interface. The proxy must preserve the original `Host`
header:

```powershell
.\.venv\Scripts\coding-agent-harness.exe web --origin https://demo.example.com --host 127.0.0.1 --port 8000
```

The application does not trust `Forwarded` or any `X-Forwarded-*` header.
Do not use those headers to make the application believe a request was HTTPS
or targeted a different host.

For a direct public bind, supply both TLS files. Startup rejects a public bind
without the complete certificate/key pair:

```powershell
.\.venv\Scripts\coding-agent-harness.exe web --origin https://demo.example.com --host 0.0.0.0 --port 8443 --tls-cert cert.pem --tls-key key.pem
```

### Request Safety and Local Testing

`GET /` issues a Secure, HttpOnly, SameSite=Strict `__Host-cah_csrf` cookie
and renders the matching hidden nonce. A run POST accepts only
`application/x-www-form-urlencoded` with exactly that `csrf_token` field:
there are no business fields in the request body. The server validates the
fixed scenario path, CSRF nonce, Origin, and Host before creating run
resources.

For local automated checks, the Web UI is exercised in-process using FastAPI
`TestClient` with an HTTPS `base_url`; no listening server is required:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\web -q
```

This is not a public deployment. It has no Provider/keyring/Git remote
integration and exposes no approve, reject, or resume endpoint.
