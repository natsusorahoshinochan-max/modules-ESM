#!/usr/bin/env python3
"""Run an explicit, isolated backend verification tier."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT_VARIABLES = (
    "PROTEIN_WORKBENCH_PROJECT_ROOT",
    "PROTEIN_WORKBENCH_CACHE_ROOT",
    "PROTEIN_WORKBENCH_OUTPUT_ROOT",
    "PROTEIN_WORKBENCH_RUN_ROOT",
)


@dataclass(frozen=True)
class Tier:
    pytest_args: tuple[str, ...]
    requires_provider_evidence: bool = False


TIERS = {
    "routine": Tier((
        "tests",
        "-m",
        "not acceptance and not installed_package "
        "and not deterministic_acceptance "
        "and not live_provider and not local_provider "
        "and not slow and not scientific_repro",
    )),
    "deterministic-acceptance": Tier((
        "tests/deterministic_acceptance",
        "-m",
        "deterministic_acceptance",
    )),
    "installed-package": Tier((
        "tests/test_installable_backend.py",
        "-m",
        "installed_package",
    )),
    "scientific-repro": Tier((
        "tests/test_esm3.py::TestESM3Adapter::test_prompt_to_esm_protein_basic",
    )),
    "mocked-workflow": Tier((
        "tests/test_e2e_seed_workflow.py",
        "tests/test_integration_3gb1.py",
    )),
    "local-provider": Tier((
        "tests/acceptance",
        "-m",
        "local_provider and not slow",
    ), requires_provider_evidence=True),
    "heavy-model": Tier((
        "tests/acceptance",
        "-m",
        "local_provider and slow",
    ), requires_provider_evidence=True),
    "live-provider": Tier((
        "tests/acceptance",
        "-m",
        "live_provider",
    ), requires_provider_evidence=True),
}

SAFE_PYTEST_SELECTOR = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\[[A-Za-z0-9_.-]+\])?"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one isolated Protein Workbench backend verification tier."
    )
    parser.add_argument("tier", choices=TIERS)
    parser.add_argument(
        "pytest_targets",
        nargs=argparse.REMAINDER,
        help="optional pytest paths after --; the tier marker contract is retained",
    )
    args = parser.parse_args()
    if args.pytest_targets[:1] == ["--"]:
        args.pytest_targets = args.pytest_targets[1:]
    for target in args.pytest_targets:
        target_parts = target.split("::")
        test_path, selectors = target_parts[0], target_parts[1:]
        supplied = Path(test_path)
        secret_like = target.lower()
        if (
            not target
            or target.startswith("-")
            or "\x00" in target
            or "\n" in target
            or "\r" in target
            or supplied.is_absolute()
            or ".." in supplied.parts
            or supplied.parts[:1] != ("tests",)
            or any(
                SAFE_PYTEST_SELECTOR.fullmatch(selector) is None
                for selector in selectors
            )
            or any(
                marker in secret_like
                for marker in (
                    "api_key=",
                    "apikey=",
                    "authorization=",
                    "password=",
                    "secret=",
                    "token=",
                )
            )
        ):
            parser.error(
                "pytest targets must be non-secret repo-relative paths "
                "beneath tests/"
            )
        resolved = (PROJECT_ROOT / supplied).resolve()
        if (
            not resolved.is_relative_to((PROJECT_ROOT / "tests").resolve())
            or not resolved.exists()
        ):
            parser.error(
                "pytest targets must resolve to existing paths beneath tests/"
            )
    return args


def _junit_counts(path: Path) -> tuple[int, int, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
    failures = sum(
        int(suite.attrib.get("failures", "0"))
        + int(suite.attrib.get("errors", "0"))
        for suite in suites
    )
    skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
    return tests, failures, skipped


def _sanitize_junit(path: Path) -> None:
    """Retain counts and test identities without failure text or host data."""
    tree = ET.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(
        root.findall("testsuite")
    )
    for suite in suites:
        suite.attrib.pop("hostname", None)
    for element in root.iter():
        if element.tag in {"failure", "error"}:
            element.attrib.clear()
            element.attrib["message"] = "details redacted"
            element.text = "Failure details were emitted only to the live console."
        elif element.tag in {"system-out", "system-err"}:
            element.attrib.clear()
            element.text = "captured output redacted"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    path.chmod(0o600)


def main() -> int:
    args = _parse_args()
    tier = TIERS[args.tier]
    print(f"BACKEND VERIFICATION TIER: {args.tier}", flush=True)
    print(f"PROJECT ENVIRONMENT: {sys.executable}", flush=True)
    results_root = Path(
        os.environ.get(
            "PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT",
            PROJECT_ROOT / "verification-results",
        )
    ).expanduser().resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    result_dir = results_root / args.tier / f"{run_id}-{os.getpid()}"
    result_dir.mkdir(parents=True, mode=0o700)
    result_dir.chmod(0o700)
    print(f"RETAINED VERIFICATION RESULT: {result_dir}", flush=True)

    with tempfile.TemporaryDirectory(
        prefix=f"protein-workbench-{args.tier}-"
    ) as temporary_root:
        base = Path(temporary_root)
        env = os.environ.copy()
        for variable in ROOT_VARIABLES:
            name = variable.removeprefix("PROTEIN_WORKBENCH_").removesuffix("_ROOT")
            root = base / name.lower()
            root.mkdir()
            env[variable] = str(root)
        env["PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED"] = "1"
        env["PROTEIN_WORKBENCH_VERIFICATION_TIER"] = args.tier
        if args.tier == "deterministic-acceptance":
            for variable in (
                "PROTEIN_WORKBENCH_CANONICAL_WORKFLOW",
                "PROTEIN_WORKBENCH_CANONICAL_UI",
                "PROTEIN_WORKBENCH_CANONICAL_VERSION",
                "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
                "PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL",
            ):
                env.pop(variable, None)

        call_evidence = result_dir / "provider-calls.jsonl"
        env["PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE"] = str(call_evidence)
        if tier.requires_provider_evidence:
            env["PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL"] = "1"

        pytest_args = list(tier.pytest_args)
        if args.pytest_targets:
            marker_args = (
                pytest_args[pytest_args.index("-m"):]
                if "-m" in pytest_args
                else []
            )
            pytest_args = [*args.pytest_targets, *marker_args]

        junit_path = result_dir / "pytest.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "-ra",
            f"--junitxml={junit_path}",
            *pytest_args,
        ]
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
        )
        transcript_path = result_dir / "command-transcript.txt"
        display_command = [
            "$PROJECT_ROOT/.venv/bin/python"
            if item == sys.executable
            else (
                "--junitxml=$RESULT_DIR/pytest.xml"
                if item == f"--junitxml={junit_path}"
                else item
            )
            for item in command
        ]
        transcript_path.write_text(
            "cwd=$PROJECT_ROOT\n"
            f"$ {shlex.join(display_command)}\n"
            f"return_code={completed.returncode}\n"
        )
        transcript_path.chmod(0o600)

        if not junit_path.exists():
            print("BACKEND VERIFICATION RESULT: failed (no JUnit result)", flush=True)
            return completed.returncode or 1

        _sanitize_junit(junit_path)
        tests, failures, skipped = _junit_counts(junit_path)
        with transcript_path.open("a") as transcript:
            transcript.write(
                f"tests={tests} failures={failures} skipped={skipped}\n"
            )
        if call_evidence.exists():
            call_evidence.chmod(0o600)
        if skipped:
            print(
                "BACKEND VERIFICATION RESULT: incomplete "
                f"({skipped} skipped test(s); skips cannot satisfy this tier)",
                flush=True,
            )
            return 3
        if completed.returncode != 0 or failures:
            print("BACKEND VERIFICATION RESULT: failed", flush=True)
            return completed.returncode or 1
        if tests == 0:
            print("BACKEND VERIFICATION RESULT: incomplete (no tests ran)", flush=True)
            return 3
        if tier.requires_provider_evidence and (
            not call_evidence.exists() or not call_evidence.read_text().strip()
        ):
            print(
                "BACKEND VERIFICATION RESULT: incomplete "
                "(no provider-call evidence was recorded)",
                flush=True,
            )
            return 3

        print("BACKEND VERIFICATION RESULT: passed", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
