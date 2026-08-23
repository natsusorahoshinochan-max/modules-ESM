"""Build one installed artifact and run copied acceptance tests against it."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import site
import subprocess
import sys
from xml.etree import ElementTree

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class InstalledArtifact:
    wheel: Path
    sdist: Path
    python: Path
    run_root: Path


def build_artifacts(output_dir: Path) -> tuple[Path, Path]:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "verification.build",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    wheels = tuple(output_dir.glob("protein_workbench-*.whl"))
    sdists = tuple(output_dir.glob("protein_workbench-*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    return wheels[0], sdists[0]


@pytest.fixture(scope="session")
def installed_artifact(
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledArtifact:
    root = tmp_path_factory.mktemp("installed-v2-artifact")
    frozen_artifact_dir = os.environ.get(
        "PROTEIN_WORKBENCH_FROZEN_ARTIFACT_DIR"
    )
    if frozen_artifact_dir is None:
        wheel, sdist = build_artifacts(root / "dist")
    else:
        artifact_root = Path(frozen_artifact_dir).resolve()
        wheels = tuple(artifact_root.glob("*.whl"))
        sdists = tuple(artifact_root.glob("*.tar.gz"))
        assert len(wheels) == len(sdists) == 1
        wheel, sdist = wheels[0], sdists[0]
    environment = root / "environment"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            str(environment),
        ],
        check=True,
    )
    python = environment / "bin" / "python"
    dependency_site = Path(site.getsitepackages()[0]).resolve()
    installed_site = environment / "lib" / "python3.12" / "site-packages"
    dependency_paths = [str(dependency_site)]
    for path_file in dependency_site.glob("*.pth"):
        for line in path_file.read_text(encoding="utf-8").splitlines():
            candidate = line.strip()
            if (
                candidate
                and not candidate.startswith("import ")
                and Path(candidate).is_absolute()
                and Path(candidate).exists()
                and "protein_workbench" not in candidate
            ):
                dependency_paths.append(candidate)
    (installed_site / "protein-workbench-locked-dependencies.pth").write_text(
        "\n".join(dict.fromkeys(dependency_paths)) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            str(wheel),
        ],
        cwd=root,
        check=True,
    )
    run_root = root / "outside-source"
    run_root.mkdir()
    return InstalledArtifact(wheel, sdist, python, run_root)


def _copy_external_acceptance_tree(destination: Path) -> Path:
    destination.mkdir(parents=True)
    shutil.copy2(
        PROJECT_ROOT / "pyproject.toml",
        destination / "pyproject.toml",
    )
    shutil.copytree(
        PROJECT_ROOT / "tests",
        destination / "tests",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(PROJECT_ROOT / "pdbs", destination / "pdbs")
    fixture_root = destination / "modules" / "solubility" / "fixtures"
    fixture_root.parent.mkdir(parents=True)
    shutil.copytree(
        PROJECT_ROOT / "modules" / "solubility" / "fixtures",
        fixture_root,
    )
    return destination / "tests"


_EXTERNAL_ACCEPTANCE_BOOTSTRAP = """
from pathlib import Path
import os
import sys
import core
import datatypes
import examples
import modules
import pdbs
import protein_workbench_public
source = Path(os.environ["PW_SOURCE_ROOT"]).resolve()
for package in (
    core,
    datatypes,
    examples,
    modules,
    pdbs,
    protein_workbench_public,
):
    assert not Path(package.__file__).resolve().is_relative_to(source)
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
"""


def run_external_acceptance(
    installed: InstalledArtifact,
    tmp_path: Path,
    *,
    selectors: tuple[str, ...],
    environment: dict[str, str],
    timeout_seconds: int,
) -> str:
    copied_tests = _copy_external_acceptance_tree(
        tmp_path / "external-suite"
    )
    junit = tmp_path / "external.xml"
    targets = [copied_tests.parent / selector for selector in selectors]
    completed = subprocess.run(
        [
            str(installed.python),
            "-I",
            "-c",
            _EXTERNAL_ACCEPTANCE_BOOTSTRAP,
            "-o",
            "addopts=",
            "-q",
            "--junitxml",
            str(junit),
            *(str(target) for target in targets),
        ],
        cwd=copied_tests.parent,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout_seconds,
    )
    assert completed.returncode == 0, completed.stdout
    root = ElementTree.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(
        int(suite.attrib.get("failures", 0))
        + int(suite.attrib.get("errors", 0))
        for suite in suites
    )
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    assert tests > 0 and failures == 0 and skipped == 0, completed.stdout
    return completed.stdout
