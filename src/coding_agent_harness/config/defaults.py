"""Built-in safety policy and non-overridable absolute limits."""

MAX_TIMEOUT_SECONDS = 600
MAX_FILES = 20
MAX_CHANGED_LINES = 2_000
MAX_SINGLE_FILE_BYTES = 1_048_576

BUILTIN_SENSITIVE_PATHS = (".env", ".env.*", "id_rsa", "id_ed25519", "*.pem", "*.key", "harness-data/**")
BUILTIN_DIAGNOSTICS = ("ruff_check", "mypy_check")
BUILTIN_MEMORY_TYPES = ("project_rule", "user_constraint", "repair_summary", "human_decision", "known_issue")

BUILTIN_CONFIG = {
    "schema_version": 1,
    "llm": {"provider": "openai", "model": "configured-by-user"},
    "tests": {"default_command": ["python", "-m", "pytest", "-q"], "timeout_seconds": 120},
    "limits": {"max_feedback_rounds": 8, "max_actions": 40, "history_window": 8, "max_no_progress": 2, "max_changed": 2, "max_process_output_bytes": 1_048_576, "max_llm_feedback_bytes": 32_768, "max_read_file_bytes": 524_288, "max_search_results": 200},
    "patch": {"approval_file_threshold": 5, "approval_line_threshold": 300},
    "paths": {"protected": ["tests/**", "**/test_*.py", "**/*_test.py", "**/conftest.py", "pytest.ini", "tox.ini", "pyproject.toml", "setup.cfg"], "sensitive": list(BUILTIN_SENSITIVE_PATHS)},
    "diagnostics": {"allowed_commands": list(BUILTIN_DIAGNOSTICS)},
    "memory": {"allowed_types": list(BUILTIN_MEMORY_TYPES), "max_items_per_context": 10, "max_context_bytes": 8192},
}
