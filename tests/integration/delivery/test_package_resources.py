from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tarfile
import venv
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "coding_agent_harness"
RESOURCE_FILES = (
    "demo/resources/feedback_success/calculator.py",
    "demo/resources/feedback_success/tests/test_calculator.py",
    "demo/resources/governance_denied/calculator.py",
    "demo/resources/governance_denied/tests/test_calculator.py",
    "demo/resources/human_review_pause/service.py",
    "demo/resources/human_review_pause/tests/test_service.py",
    "web/templates/base.html",
    "web/templates/scenarios.html",
    "web/templates/result.html",
    "web/static/app.js",
)
RUNTIME_DEPENDENCIES = (
    "pydantic",
    "typer",
    "fastapi",
    "uvicorn",
    "jinja2",
    "openai",
    "keyring",
    "platformdirs",
)
FORBIDDEN_MEMBER_PARTS = (".git", ".pytest_cache", ".ruff_cache", "__pycache__")
FORBIDDEN_DEVELOPMENT_ROOTS = (
    "tests",
    "docs",
    ".github",
    ".gitlab-ci.yml",
    "AGENT_LOG.md",
    "docs/superpowers",
    "docs/assignment",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_digests() -> dict[str, str]:
    return {
        relative: _sha256(ROOT / "src" / PACKAGE / relative)
        for relative in RESOURCE_FILES
    }


@pytest.fixture(scope="module")
def built_distributions(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    output = tmp_path_factory.mktemp("package-resources") / "dist"
    subprocess.run(
        (sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output)),
        cwd=ROOT,
        check=True,
        shell=False,
    )
    return (
        next(output.glob("*.whl")),
        next(output.glob("*.tar.gz")),
    )


def _archive_members(archive: Path) -> Iterator[tuple[str, bytes]]:
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as wheel:
            yield from ((member, wheel.read(member)) for member in wheel.namelist())
        return

    with tarfile.open(archive, "r:gz") as sdist:
        for member in sdist.getmembers():
            if member.isfile():
                extracted = sdist.extractfile(member)
                assert extracted is not None
                yield member.name, extracted.read()


def _archive_resource_digests(archive: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    marker = f"{PACKAGE}/"
    for member, contents in _archive_members(archive):
        position = member.find(marker)
        if position >= 0:
            relative = member[position + len(marker) :]
            if relative in RESOURCE_FILES:
                digests[relative] = hashlib.sha256(contents).hexdigest()
    return digests


def _copy_runtime_distributions(target: Path) -> None:
    pending = list(RUNTIME_DEPENDENCIES)
    copied: set[str] = set()

    while pending:
        distribution_name = pending.pop()
        distribution = importlib.metadata.distribution(distribution_name)
        normalized_name = distribution.metadata["Name"].lower().replace("_", "-")
        if normalized_name in copied:
            continue
        copied.add(normalized_name)

        for requirement_text in distribution.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            pending.append(requirement.name)

        for file in distribution.files or ():
            source = distribution.locate_file(file)
            if source.is_file():
                destination = target / file
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)


def test_wheel_and_sdist_contain_source_identical_demo_and_web_resources(
    built_distributions: tuple[Path, Path],
) -> None:
    source_digests = _source_digests()

    for archive in built_distributions:
        assert _archive_resource_digests(archive) == source_digests


def test_distributions_exclude_caches_absolute_paths_and_development_files(
    built_distributions: tuple[Path, Path],
) -> None:
    root_text = str(ROOT).replace("\\", "/").lower()

    for archive in built_distributions:
        for member, _ in _archive_members(archive):
            path = PurePosixPath(member)
            parts = path.parts
            assert not path.is_absolute()
            assert not PureWindowsPath(member).is_absolute()
            assert not any(part in FORBIDDEN_MEMBER_PARTS for part in parts)
            assert root_text not in member.lower()
            package_index = parts.index(PACKAGE) if PACKAGE in parts else None
            if package_index is None:
                relative = "/".join(parts[1:] if archive.suffix == ".gz" else parts)
                assert not any(
                    relative == forbidden or relative.startswith(f"{forbidden}/")
                    for forbidden in FORBIDDEN_DEVELOPMENT_ROOTS
                )


def test_isolated_install_reads_packaged_resources_and_runtime_dependencies(
    built_distributions: tuple[Path, Path], tmp_path: Path
) -> None:
    wheel, _ = built_distributions
    environment_root = tmp_path / "isolated-environment"
    venv.EnvBuilder(with_pip=True).create(environment_root)
    venv_python = environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    target = Path(
        subprocess.run(
            (
                str(venv_python),
                "-I",
                "-c",
                "import site; print(site.getsitepackages()[0])",
            ),
            check=True,
            shell=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    _copy_runtime_distributions(target)
    subprocess.run(
        (
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-compile",
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ),
        check=True,
        shell=False,
    )
    script = """
import hashlib
import importlib
import importlib.resources
import importlib.metadata
import json
import os

package = importlib.import_module('coding_agent_harness')
files = importlib.resources.files(package)
resources = json.loads(os.environ['CAH_RESOURCE_FILES'])
dependencies = json.loads(os.environ['CAH_RUNTIME_DEPENDENCIES'])
result = {
    'package_path': str(package.__file__),
    'digests': {
        resource: hashlib.sha256(files.joinpath(resource).read_bytes()).hexdigest()
        for resource in resources
    },
    'dependencies': {dependency: bool(importlib.import_module(dependency)) for dependency in dependencies},
    'dependency_paths': {
        dependency: str(importlib.import_module(dependency).__file__)
        for dependency in dependencies
    },
    'requires_dist': importlib.metadata.metadata('coding-agent-harness').get_all('Requires-Dist'),
}
print(json.dumps(result))
"""
    environment = {
        **os.environ,
        "CAH_RESOURCE_FILES": json.dumps(RESOURCE_FILES),
        "CAH_RUNTIME_DEPENDENCIES": json.dumps(RUNTIME_DEPENDENCIES),
    }
    completed = subprocess.run(
        (str(venv_python), "-I", "-c", script),
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    result = json.loads(completed.stdout)

    assert Path(result["package_path"]).resolve().is_relative_to(target.resolve())
    assert result["digests"] == _source_digests()
    assert result["dependencies"] == {
        dependency: True for dependency in RUNTIME_DEPENDENCIES
    }
    assert all(
        Path(module_path).resolve().is_relative_to(target.resolve())
        for module_path in result["dependency_paths"].values()
    )
    assert result["requires_dist"][:8] == [
        "pydantic<2.14,>=2.13.4",
        "typer<0.28,>=0.27.1",
        "fastapi<0.142,>=0.141.1",
        "uvicorn<0.53,>=0.52.1",
        "jinja2<3.2,>=3.1.6",
        "openai<2.54,>=2.53.0",
        "keyring<25.8,>=25.7.0",
        "platformdirs<4.12,>=4.11.0",
    ]
