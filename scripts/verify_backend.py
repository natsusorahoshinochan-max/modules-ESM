#!/usr/bin/env python3
"""Run one isolated verification tier for the v2-only backend."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
import secrets
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

from modules.acceptance_verification import ACCEPTANCE_TIER_CONTRACTS


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
TERMINATION_GRACE_SECONDS = 5.0
MAX_CONSOLE_BYTES = 16 * 1024 * 1024
MAX_JUNIT_BYTES = 16 * 1024 * 1024
OUTPUT_CHUNK_SIZE = 64 * 1024
PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@dataclass(frozen=True)
class Tier:
    pytest_arguments: tuple[str, ...]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    zero_skip: bool = False
    retain_evidence_bundle: bool = False


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
            "test_readiness_rejects_before_fold_call"
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
            "test_native_plddt_is_statically_scaled_and_projects_protein_tokens"
        ),
        (
            "tests/test_folding_v2.py::"
            "test_remote_provider_native_result_translates_to_canonical_confidence"
        ),
        (
            "tests/test_folding_v2.py::"
            "test_local_provider_native_result_translates_to_canonical_confidence"
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
    "installed-package": Tier((
        (
            "tests/test_installed_backend_v2.py::"
            "test_built_artifact_is_reproducible_complete_and_fixture_free"
        ),
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_protocol_catalog_identity_and_"
            "separate_availability"
        ),
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_backend_completes_full_public_v2_journey"
        ),
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_proteinmpnn_lifecycle_requires_one_model_load"
        ),
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_proteinmpnn_lifecycle_accepts_one_model_load"
        ),
    )),
    **{
        name: Tier(
            contract.pytest_arguments,
            timeout_seconds=contract.timeout_seconds,
            zero_skip=True,
            retain_evidence_bundle=True,
        )
        for name, contract in ACCEPTANCE_TIER_CONTRACTS.items()
    },
}


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


def _bounded_junit_summary(path: Path) -> tuple[int, int, int, bytes]:
    if not path.is_file():
        raise ValueError("JUnit result is missing")
    if path.stat().st_size > MAX_JUNIT_BYTES:
        raise ValueError("JUnit result exceeds the retained size bound")
    root = ET.parse(path).getroot()
    suites = (
        [root]
        if root.tag.rsplit("}", 1)[-1] == "testsuite"
        else [
            child
            for child in root
            if child.tag.rsplit("}", 1)[-1] == "testsuite"
        ]
    )
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failure_count = sum(
        int(suite.attrib.get("failures", 0)) for suite in suites
    )
    error_count = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
    failures = failure_count + error_count
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    summary = ET.Element(
        "testsuite",
        {
            "tests": str(tests),
            "failures": str(failure_count),
            "errors": str(error_count),
            "skipped": str(skipped),
        },
    )
    return tests, failures, skipped, ET.tostring(
        summary,
        encoding="utf-8",
        xml_declaration=True,
    )


def _bounded_junit_diagnostics(
    path: Path,
    *,
    staging_root: Path,
    environment: Mapping[str, str],
) -> bytes:
    """Retain exact bounded JUnit diagnostics after local-path redaction."""
    if not path.is_file():
        raise ValueError("JUnit result is missing")
    if path.stat().st_size > MAX_JUNIT_BYTES:
        raise ValueError("JUnit result exceeds the retained size bound")
    ET.parse(path)
    diagnostic = _redacted_diagnostic(
        path.read_text(encoding="utf-8"),
        staging_root=staging_root,
        environment=environment,
    ).encode()
    if len(diagnostic) > MAX_JUNIT_BYTES:
        raise ValueError("JUnit result exceeds the retained size bound")
    return diagnostic


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except (PermissionError, ProcessLookupError):
        return False
    return True


@contextmanager
def _record_interruptions() -> Iterator[dict[str, int | None]]:
    state: dict[str, int | None] = {"signal": None}

    def record(signum: int, _frame: object) -> None:
        state["signal"] = signum

    previous = {
        signum: signal.getsignal(signum)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    for signum in previous:
        signal.signal(signum, record)
    try:
        yield state
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except (PermissionError, ProcessLookupError):
        if process.poll() is None:
            process.wait()
        return

    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    while (
        _process_group_exists(process_group_id)
        and time.monotonic() < deadline
    ):
        process.poll()
        time.sleep(0.01)
    if _process_group_exists(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass
    if process.poll() is None:
        try:
            process.wait()
        except ProcessLookupError:
            pass


def _drain_output(
    stream: io.BufferedIOBase,
    captured: bytearray,
    state: dict[str, bool],
) -> None:
    try:
        while chunk := stream.read(OUTPUT_CHUNK_SIZE):
            remaining = MAX_CONSOLE_BYTES - len(captured)
            if remaining > 0:
                captured.extend(chunk[:remaining])
            if len(chunk) > remaining:
                state["exceeded"] = True
    except (OSError, ValueError):
        state["read_error"] = True


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


def _redacted_diagnostic(
    value: str,
    *,
    staging_root: Path,
    environment: Mapping[str, str],
) -> str:
    """Remove credentials and machine-local configured paths from diagnostics."""
    redacted = _sanitized(value, staging_root=staging_root)
    credential_values: list[str] = []
    for name, configured in environment.items():
        if not configured:
            continue
        if any(marker in name for marker in ("TOKEN", "SECRET", "API_KEY")):
            if name.endswith("_FILE"):
                credential_path = Path(configured)
                try:
                    if (
                        credential_path.is_file()
                        and credential_path.stat().st_size <= 1024 * 1024
                    ):
                        secret = credential_path.read_text(
                            encoding="utf-8"
                        ).strip()
                        if secret:
                            credential_values.append(secret)
                except (OSError, UnicodeError):
                    pass
            else:
                credential_values.append(configured)
    for secret in sorted(set(credential_values), key=len, reverse=True):
        redacted = redacted.replace(secret, "$REDACTED_CREDENTIAL")
    path_suffixes = ("_BINARY", "_DIR", "_FILE", "_PATH", "_ROOT")
    path_variables = {
        name: configured
        for name, configured in environment.items()
        if configured
        and (
            name in ROOT_VARIABLES
            or name.endswith(path_suffixes)
            or name in {"HF_HUB_CACHE", "HF_HOME", *PROXY_VARIABLES}
        )
    }
    for name, configured in sorted(
        path_variables.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        redacted = redacted.replace(configured, f"${name}")
    return redacted


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
        if tier.retain_evidence_bundle:
            evidence_staging = staging_root / "acceptance-evidence"
            evidence_staging.mkdir(mode=0o700)
            env["PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_STAGING"] = str(
                evidence_staging
            )
        env.pop("PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE", None)
        env.pop("PROTEIN_WORKBENCH_PROVIDER_EVIDENCE_SCOPE", None)
        env.pop("PYTEST_ADDOPTS", None)

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
        with _record_interruptions() as interruption:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            assert process.stdout is not None
            captured = bytearray()
            output_state = {"exceeded": False, "read_error": False}
            reader = threading.Thread(
                target=_drain_output,
                args=(process.stdout, captured, output_state),
                daemon=True,
            )
            reader.start()
            timed_out = False
            deadline = time.monotonic() + tier.timeout_seconds
            while process.poll() is None:
                if interruption["signal"] is not None:
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(0.05)
            _terminate_group(process)
        interrupted = interruption["signal"] is not None
        reader.join(timeout=5)
        if reader.is_alive():
            process.stdout.close()
            reader.join(timeout=1)
        if reader.is_alive():
            output_state["read_error"] = True
        output = captured.decode(errors="replace")
        print(output, end="", flush=True)

        junit_summary: bytes | None = None
        junit_diagnostics: bytes | None = None
        junit_valid = False
        try:
            tests, failures, skipped, junit_summary = (
                _bounded_junit_summary(junit_path)
            )
            junit_diagnostics = _bounded_junit_diagnostics(
                junit_path,
                staging_root=staging_root,
                environment=env,
            )
            junit_valid = True
        except (OSError, ET.ParseError, ValueError):
            tests, failures, skipped = 0, 1, 0
        resource_warning = RESOURCE_CLEANUP_WARNING in output
        passed = (
            process.returncode == 0
            and not interrupted
            and not timed_out
            and not output_state["exceeded"]
            and not output_state["read_error"]
            and not resource_warning
            and junit_valid
            and failures == 0
            and (not tier.zero_skip or skipped == 0)
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
        evidence_staging = staging_root / "acceptance-evidence"
        if tier.retain_evidence_bundle:
            _write_private(
                evidence_staging / "tier-result.json",
                json.dumps(
                    {
                        "schema_namespace": (
                            "protein-workbench-verification-tier-result/v2"
                        ),
                        "tier": tier_name,
                        "source_revision": revision,
                        "tests": tests,
                        "failures": failures,
                        "skipped": skipped,
                        "passed": passed,
                        "interrupted": interrupted,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n",
            )
        if (
            tier.retain_evidence_bundle
            and evidence_staging.is_dir()
        ):
            shutil.copytree(
                evidence_staging,
                result_dir / "evidence",
            )
        transcript = (
            "cwd=$PROJECT_ROOT\n"
            + "$ "
            + " ".join(_sanitized(part, staging_root=staging_root) for part in command)
            + "\n"
            + f"return_code={process.returncode}\n"
            + f"tests={tests} failures={failures} skipped={skipped}\n"
            + f"timed_out={str(timed_out).lower()}\n"
            + f"interrupted={str(interrupted).lower()}\n"
            + (
                "console_output_exceeded="
                f"{str(output_state['exceeded']).lower()}\n"
            )
            + f"console_read_error={str(output_state['read_error']).lower()}\n"
            + f"junit_valid={str(junit_valid).lower()}\n"
            + f"resource_cleanup_warning={str(resource_warning).lower()}\n"
        )
        _write_private(
            result_dir / "command-transcript.txt",
            transcript.encode(),
        )
        _write_private(
            result_dir / "console-output.txt",
            _redacted_diagnostic(
                output,
                staging_root=staging_root,
                environment=env,
            ).encode(),
        )
        _write_private(
            result_dir / "environment-summary.json",
            json.dumps(
                {
                    "schema_version": "2.1.0",
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
                    "evidence_bundle_required": (
                        tier.retain_evidence_bundle
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
        if junit_summary is not None:
            _write_private(result_dir / "pytest.xml", junit_summary)
        if junit_diagnostics is not None:
            _write_private(
                result_dir / "pytest-diagnostics.xml",
                junit_diagnostics,
            )

        print(f"RETAINED VERIFICATION RESULT: {result_dir}", flush=True)
        if passed:
            print("BACKEND VERIFICATION RESULT: passed", flush=True)
            return 0
        reason = (
            "interrupted"
            if interrupted
            else "multiprocessing resource cleanup warning"
            if resource_warning
            else "timeout"
            if timed_out
            else "console output exceeded retained size bound"
            if output_state["exceeded"]
            else "console output read failure"
            if output_state["read_error"]
            else "invalid or oversized JUnit result"
            if not junit_valid
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
    return run(args.tier, tuple(override))


if __name__ == "__main__":
    raise SystemExit(main())
