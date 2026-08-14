#!/usr/bin/env python3
"""Run one isolated verification tier for the v2-only backend."""

from __future__ import annotations

import argparse
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


@dataclass(frozen=True)
class Tier:
    pytest_arguments: tuple[str, ...]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    zero_skip: bool = False
    clean_source: bool = False
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
    )),
    "installed-biohub-esmc": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esmc_gate"
        ),),
        zero_skip=True,
    ),
    "installed-biohub-esm3": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esm3_gate"
        ),),
        timeout_seconds=40 * 60,
        zero_skip=True,
    ),
    "installed-biohub-esmfold2": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esmfold2_gate"
        ),),
        timeout_seconds=35 * 60,
        zero_skip=True,
    ),
    "installed-local-esm3": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_local_esm3_gate"
        ),),
        zero_skip=True,
    ),
    "installed-local-esmfold2": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_local_esmfold2_gate"
        ),),
        timeout_seconds=105 * 60,
        zero_skip=True,
    ),
    "installed-proteinmpnn": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_proteinmpnn_gate"
        ),),
        timeout_seconds=75 * 60,
        zero_skip=True,
    ),
    "installed-mkdssp": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_mkdssp_gate"
        ),),
        zero_skip=True,
    ),
    "installed-simplefold-folding": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_simplefold_folding_gate"
        ),),
        zero_skip=True,
    ),
    "installed-simplefold-confidence": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_simplefold_confidence_gate"
        ),),
        zero_skip=True,
    ),
    "installed-soluprot": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_soluprot_gate"
        ),),
        zero_skip=True,
    ),
    "installed-protein-sol": Tier(
        ((
            "tests/test_installed_backend_v2.py::"
            "test_installed_protein_sol_gate"
        ),),
        zero_skip=True,
    ),
    "fresh-remote-3gb1": Tier(
        ((
            "tests/test_fresh_remote_3gb1_v2.py::"
            "test_fresh_remote_3gb1_installed_public_run_"
            "retains_auditable_bundle"
        ),),
        timeout_seconds=90 * 60,
        zero_skip=True,
        clean_source=True,
        retain_evidence_bundle=True,
    ),
    "provider-isolation": Tier((
        (
            "tests/test_folding_v2.py::"
            "test_missing_local_esmfold2_stays_fail_closed_without_hiding_remote"
        ),
        (
            "tests/test_esm3_local_v2.py::"
            "test_local_runtime_rejects_model_replacement_and_stale_configuration"
        ),
        (
            "tests/test_esm3_local_v2.py::"
            "test_local_readiness_rechecks_model_identity_before_any_cache_lookup"
        ),
        (
            "tests/test_simplefold_folding_v2.py::"
            "test_simplefold_readiness_validates_assets_without_hiding_siblings"
        ),
        (
            "tests/test_simplefold_confidence_v2.py::"
            "test_confidence_readiness_has_exact_asset_closure_and_"
            "invalidates_replacement"
        ),
        (
            "tests/test_solubility_v2.py::"
            "test_soluprot_startup_is_lazy_and_keeps_unavailable_siblings_visible"
        ),
        (
            "tests/test_solubility_v2.py::"
            "test_soluprot_runtime_probe_rejects_transitive_dependency_tree_drift"
        ),
        (
            "tests/test_solubility_v2.py::"
            "test_full_readiness_failure_does_not_block_no_tm"
        ),
        (
            "tests/test_protein_sol_v2.py::"
            "test_protein_sol_exact_source_tree_controls_readiness"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_changed_credential_is_reobserved_and_rejects_stale_green"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_reusable_readiness_proof_requires_identity_scope_age_"
            "fingerprint_and_invalidation"
        ),
        (
            "tests/test_module_packages_v2.py::"
            "test_missing_optional_dependency_does_not_hide_available_sibling"
        ),
        (
            "tests/acceptance/test_soluprot_v2.py::"
            "test_stale_no_tm_asset_replacement_invalidates_readiness"
        ),
    )),
    "security-failure": Tier((
        (
            "tests/test_protein_io_artifacts_v2.py::"
            "test_artifact_retrieval_rejects_tampering_symlinks_and_traversal"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_failed_readiness_rejects_before_factory_and_redacts_environment"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_cleanup_failure_is_bounded_and_does_not_rewrite_engine_success"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_artifact_retrieval_rejects_cross_scope_tamper_and_symlink"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_symlinked_run_workspace_fails_before_readiness_without_outside_write"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_reusable_proof_is_cached_only_after_durable_attestation"
        ),
        (
            "tests/test_run_execution_v2.py::"
            "test_public_run_exposes_no_node_subset_when_transaction_commit_fails"
        ),
        (
            "tests/test_result_cache_v2.py::"
            "test_conflicting_output_for_one_result_identity_fails_without_overwrite"
        ),
        (
            "tests/test_run_cancel_derive_v2.py::"
            "test_cancel_terminates_registered_process_group_children_and_temp_work"
        ),
        (
            "tests/test_run_cancel_derive_v2.py::"
            "test_cancel_and_derive_reject_cross_project_scope_with_shared_errors"
        ),
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


def _bounded_junit_summary(path: Path) -> tuple[int, int, int, bytes]:
    if path.is_symlink():
        raise ValueError("JUnit result must not be a symbolic link")
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


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except (PermissionError, ProcessLookupError):
        return False
    return True


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


def run(tier_name: str, pytest_override: tuple[str, ...]) -> int:
    tier = TIERS[tier_name]
    if tier.zero_skip and pytest_override:
        raise ValueError("installed provider gates do not accept test overrides")
    arguments = pytest_override or tier.pytest_arguments
    revision, dirty = _git_state()
    print(f"BACKEND VERIFICATION TIER: {tier_name}", flush=True)
    print(
        f"PROJECT ENVIRONMENT: {Path(sys.executable).resolve()}",
        flush=True,
    )
    if tier.clean_source and dirty:
        print(
            "BACKEND VERIFICATION RESULT: failed "
            "(fresh remote tier requires a clean source revision)",
            flush=True,
        )
        return 1

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
            env["PROTEIN_WORKBENCH_FRESH_SOURCE_REVISION"] = revision
            env["PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING"] = str(
                staging_root / "fresh-remote-3gb1-evidence"
            )
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
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(0.05)
        _terminate_group(process)
        reader.join(timeout=5)
        if reader.is_alive():
            process.stdout.close()
            reader.join(timeout=1)
        if reader.is_alive():
            output_state["read_error"] = True
        output = captured.decode(errors="replace")
        print(output, end="", flush=True)

        junit_summary: bytes | None = None
        junit_valid = False
        try:
            tests, failures, skipped, junit_summary = (
                _bounded_junit_summary(junit_path)
            )
            junit_valid = True
        except (OSError, ET.ParseError, ValueError):
            tests, failures, skipped = 0, 1, 0
        resource_warning = RESOURCE_CLEANUP_WARNING in output
        passed = (
            process.returncode == 0
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
        evidence_staging = staging_root / "fresh-remote-3gb1-evidence"
        if (
            tier.retain_evidence_bundle
            and evidence_staging.is_dir()
            and not evidence_staging.is_symlink()
        ):
            shutil.copytree(
                evidence_staging,
                result_dir / "evidence",
                symlinks=False,
            )
        transcript = (
            "cwd=$PROJECT_ROOT\n"
            + "$ "
            + " ".join(_sanitized(part, staging_root=staging_root) for part in command)
            + "\n"
            + f"return_code={process.returncode}\n"
            + f"tests={tests} failures={failures} skipped={skipped}\n"
            + f"timed_out={str(timed_out).lower()}\n"
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
                    "clean_source_required": tier.clean_source,
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

        print(f"RETAINED VERIFICATION RESULT: {result_dir}", flush=True)
        if passed:
            print("BACKEND VERIFICATION RESULT: passed", flush=True)
            return 0
        reason = (
            "multiprocessing resource cleanup warning"
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
    try:
        safe_override = _safe_override(override)
        if TIERS[args.tier].zero_skip and safe_override:
            raise ValueError(
                "installed provider gates do not accept test overrides"
            )
    except ValueError as error:
        parser.error(str(error))
    return run(args.tier, safe_override)


if __name__ == "__main__":
    raise SystemExit(main())
