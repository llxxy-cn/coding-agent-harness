"""Repository hygiene tests for the formal Task 1 skeleton."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_IGNORE_RULES = {
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_ed25519.pub",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    ".harness/",
    "harness-data/",
    "dist/",
    "build/",
    "*.egg-info/",
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".coverage",
    "htmlcov/",
    ".venv/",
    "venv/",
}


def test_gitignore_blocks_credentials_and_runtime_artifacts():
    gitignore = PROJECT_ROOT / ".gitignore"
    assert gitignore.is_file(), ".gitignore must exist at the project root"
    rules = {
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = REQUIRED_IGNORE_RULES - rules
    assert not missing, f".gitignore is missing exact rules: {sorted(missing)}"
