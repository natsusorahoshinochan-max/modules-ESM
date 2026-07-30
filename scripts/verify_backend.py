#!/usr/bin/env python3
"""Run one isolated verification tier for the v2-only backend."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import stat
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
RESOURCE_CLEANUP_WARNING = (
    "ResourceTracker called reentrantly for resource cleanup"
)
DEFAULT_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class Tier:
    pytest_arguments: tuple[str, ...]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


TIERS = {
    "routine": Tier((
        "tests",
        "-m",
        "not acceptance and not installed_package "
        "and not deterministic_acceptance "
        "and not live_provider and not local_provider "
        "and not slow and not scientific_repro",
    )),
    "examples-v2": Tier(("tests/test_repository_examples_v2.py",)),
    "deterministic-acceptance": Tier((
        "tests/test_canonical_3gb1_v2.py",
        (
            "tests/test_folding_v2.py::"
            "test_readiness_rejects_before_cache_lookup_or_fold_call"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_branch_failure_closes_every_disposition_and_unrelated_work_continues"
        ),
        (
            "tests/test_run_cancel_derive_v2.py::"
            "test_cancel_during_operation_is_idempotent_and_closes_active_evidence"
        ),
        (
            "tests/test_run_cancel_derive_v2.py::"
            "test_cancel_and_derive_reject_cross_project_scope_with_shared_errors"
        ),
        "tests/deterministic_acceptance",
        "-m",
        "deterministic_acceptance",
    )),
    "scientific-repro": Tier((
        (
            "tests/test_esm3_v2.py::"
            "test_adapter_preserves_every_representable_prompt_track_and_symbol"
        ),
    )),
    "local-esmfold2-v2-contract": Tier((
        (
            "tests/acceptance/test_esmfold2_v2.py::"
            "test_local_esmfold2_v2_source_contract_and_native_result"
        ),
        (
            "tests/test_folding_v2.py::"
            "test_native_plddt_is_statically_scaled_and_masks_invalid_tokens"
        ),
        (
            "tests/test_folding_v2.py::"
            "test_remote_and_local_provider_native_results_normalize_identically"
        ),
        (
            "tests/test_folding_v2.py::"
            "test_selected_binding_folds_without_fallback_and_publishes_exact_lineage"
            "[local]"
        ),
        (
            "tests/test_folding_v2.py::"
            "test_remote_and_local_bindings_pass_shared_contract_test_kit"
        ),
        "-m",
        "not live_provider and not local_provider",
    )),
}


def _safe_override(arguments: list[str]) -> tuple[str, ...]:
    safe: list[str] = []
    for argument in arguments:
        selector = argument.split("::", 1)[0]
        path = Path(selector)
        if (
            argument.startswith("-")
            or path.is_absolute()
            or not selector.startswith("tests/")
            or ".." in path.parts
        ):
            raise ValueError(
                "pytest overrides must be repo-relative paths beneath tests/"
            )
        safe.append(argument)
    return tuple(safe)


def _git_state() -> tuple[str, bool]:
    revision = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["/usr/bin/git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    )
    return revision, dirty


def _interpreter_digest() -> str:
    digest = hashlib.sha256()
    with Path(sys.executable).resolve().open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _junit_counts(path: Path) -> tuple[int, int, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(
        int(suite.attrib.get("failures", 0))
        + int(suite.attrib.get("errors", 0))
        for suite in suites
    )
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    return tests, failures, skipped


def _terminate_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _sanitized(
    value: str,
    *,
    staging_root: Path,
) -> str:
    return (
        value.replace(sys.executable, "$PROJECT_ENV/bin/python")
        .replace(str(Path(sys.executable).resolve()), "$PROJECT_ENV/bin/python")
        .replace(str(PROJECT_ROOT), "$PROJECT_ROOT")
        .replace(str(staging_root), "$STAGING_ROOT")
    )


def run(tier_name: str, pytest_override: tuple[str, ...]) -> int:
    tier = TIERS[tier_name]
    arguments = pytest_override or tier.pytest_arguments
    revision, dirty = _git_state()
    print(f"BACKEND VERIFICATION TIER: {tier_name}", flush=True)
    print(
        f"PROJECT ENVIRONMENT: {Path(sys.executable).resolve()}",
        flush=True,
    )

    with tempfile.TemporaryDirectory(
        prefix=f"protein-workbench-{tier_name}-"
    ) as temporary:
        staging_root = Path(temporary)
        junit_path = staging_root / "pytest.xml"
        env = os.environ.copy()
        for variable in ROOT_VARIABLES:
            root = staging_root / variable.lower()
            root.mkdir(mode=0o700)
            env[variable] = str(root)
        env["PROTEIN_WORKBENCH_VERIFICATION_TIER"] = tier_name
        env.pop("PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE", None)
        env.pop("PROTEIN_WORKBENCH_PROVIDER_EVIDENCE_SCOPE", None)

        command = [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "-ra",
            f"--junitxml={junit_path}",
            *arguments,
        ]
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        try:
            output, _ = process.communicate(timeout=tier.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_group(process)
            output, _ = process.communicate()
        print(output, end="", flush=True)

        if junit_path.is_file():
            tests, failures, skipped = _junit_counts(junit_path)
        else:
            tests, failures, skipped = 0, 1, 0
        resource_warning = RESOURCE_CLEANUP_WARNING in output
        passed = (
            process.returncode == 0
            and not timed_out
            and not resource_warning
            and failures == 0
            and tests > 0
        )

        results_root = Path(
            os.environ.get(
                "PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT",
                PROJECT_ROOT / "verification-results",
            )
        )
        result_dir = (
            results_root
            / tier_name
            / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                + f"-{os.getpid()}-{secrets.token_hex(8)}"
            )
        )
        result_dir.mkdir(parents=True, mode=0o700)
        result_dir.chmod(0o700)
        transcript = (
            "cwd=$PROJECT_ROOT\n"
            + "$ "
            + " ".join(_sanitized(part, staging_root=staging_root) for part in command)
            + "\n"
            + f"return_code={process.returncode}\n"
            + f"tests={tests} failures={failures} skipped={skipped}\n"
            + f"timed_out={str(timed_out).lower()}\n"
            + f"resource_cleanup_warning={str(resource_warning).lower()}\n"
        )
        _write_private(
            result_dir / "command-transcript.txt",
            transcript.encode(),
        )
        _write_private(
            result_dir / "environment-summary.json",
            json.dumps(
                {
                    "schema_version": "2.0.0",
                    "tier": tier_name,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "project_revision": revision,
                    "project_dirty": dirty,
                    "python": sys.version.split()[0],
                    "interpreter": str(Path(sys.executable).resolve()),
                    "interpreter_sha256": _interpreter_digest(),
                    "isolated_roots": list(ROOT_VARIABLES),
                    "historical_cache_allowed": False,
                    "parallel_provider_evidence_allowed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
        if junit_path.is_file():
            _write_private(result_dir / "pytest.xml", junit_path.read_bytes())

        print(f"RETAINED VERIFICATION RESULT: {result_dir}", flush=True)
        if passed:
            print("BACKEND VERIFICATION RESULT: passed", flush=True)
            return 0
        reason = (
            "multiprocessing resource cleanup warning"
            if resource_warning
            else "timeout"
            if timed_out
            else "test failure"
        )
        print(
            f"BACKEND VERIFICATION RESULT: failed ({reason})",
            flush=True,
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an isolated v2 backend verification tier",
    )
    parser.add_argument("tier", choices=tuple(sorted(TIERS)))
    parser.add_argument("pytest_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    override = list(args.pytest_arguments)
    if override[:1] == ["--"]:
        override = override[1:]
    try:
        safe_override = _safe_override(override)
    except ValueError as error:
        parser.error(str(error))
    return run(args.tier, safe_override)


if __name__ == "__main__":
    raise SystemExit(main())
