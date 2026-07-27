#!/usr/bin/env python3
"""Run an explicit, isolated backend verification tier."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import secrets
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.provider_contract import (
    BIOHUB_ESM3_MODEL,
    BIOHUB_ESMFOLD2_MODEL,
    LOCAL_ESM3_SNAPSHOT_REVISION,
    LOCAL_ESM3_WEIGHT_SHA256,
    PROTEINMPNN_REVISION,
    PROTEINMPNN_V_48_020_SHA256,
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_REVISION,
    ESM_SDK_REVISION,
)

ROOT_VARIABLES = (
    "PROTEIN_WORKBENCH_PROJECT_ROOT",
    "PROTEIN_WORKBENCH_CACHE_ROOT",
    "PROTEIN_WORKBENCH_OUTPUT_ROOT",
    "PROTEIN_WORKBENCH_RUN_ROOT",
)
RESOURCE_CLEANUP_WARNING = (
    "ResourceTracker called reentrantly for resource cleanup"
)
OUTPUT_CHUNK_SIZE = 64 * 1024
MAX_CONSOLE_BYTES = 16 * 1024 * 1024
MAX_JUNIT_BYTES = 16 * 1024 * 1024
TIER_TIMEOUT_SECONDS = 30 * 60
LIVE_ESM3_TEST = (
    "tests/acceptance/test_biohub_generation.py::"
    "TestBiohubGeneration::test_generate_3gb1_sequence"
)


@dataclass(frozen=True)
class Tier:
    pytest_args: tuple[str, ...]
    requires_provider_evidence: bool = False
    required_calls: frozenset[tuple[str, str]] = frozenset()
    expected_test_ids: frozenset[str] = frozenset()


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
        "tests/acceptance/test_alignment_tm.py::test_real_alignment_and_tm_score",
        "tests/acceptance/test_mkdssp.py::TestMKDSSP::test_dssp_3gb1",
        "-m",
        "local_provider and not slow",
    ), requires_provider_evidence=True, required_calls=frozenset({
        ("mkdssp", "secondary_structure"),
        ("biopython-svd", "structure_align"),
        ("tmtools", "tm_score"),
    }), expected_test_ids=frozenset({
        "tests/acceptance/test_alignment_tm.py::test_real_alignment_and_tm_score",
        "tests/acceptance/test_mkdssp.py::TestMKDSSP::test_dssp_3gb1",
    })),
    "heavy-model": Tier((
        "tests/acceptance/test_local_esm3.py::test_local_esm3_sequence_boundary",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_design_3gb1",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_score_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_fold_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_evaluate_3gb1",
        "-m",
        "local_provider and slow",
    ), requires_provider_evidence=True, required_calls=frozenset({
        ("local_open", "esm3.generate_sequence"),
        ("local-proteinmpnn", "design_sequences"),
        ("local-proteinmpnn", "score_sequence"),
        ("simplefold", "fold_sequence"),
        ("simplefold", "evaluate_structure"),
    }), expected_test_ids=frozenset({
        "tests/acceptance/test_local_esm3.py::test_local_esm3_sequence_boundary",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_design_3gb1",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_score_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_fold_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_evaluate_3gb1",
    })),
    "live-provider": Tier((
        LIVE_ESM3_TEST,
        "tests/acceptance/test_biohub_folding.py::TestBiohubFolding::test_fold_3gb1[False-False]",
        "-m",
        "live_provider",
    ), requires_provider_evidence=True, required_calls=frozenset({
        ("biohub", "esm3.generate_sequence"),
        ("biohub", "esmfold2.fold"),
    }), expected_test_ids=frozenset({
        LIVE_ESM3_TEST,
        "tests/acceptance/test_biohub_folding.py::TestBiohubFolding::test_fold_3gb1[False-False]",
    })),
}

EXPECTED_MODELS = {
    ("local_open", "esm3.generate_sequence"): "esm3_sm_open_v1",
    ("local-proteinmpnn", "design_sequences"): "v_48_020",
    ("local-proteinmpnn", "score_sequence"): "v_48_020",
    ("simplefold", "fold_sequence"): "simplefold_100M",
    ("simplefold", "evaluate_structure"): "simplefold_360M",
    ("biohub", "esm3.generate_sequence"): BIOHUB_ESM3_MODEL,
    ("biohub", "esmfold2.fold"): BIOHUB_ESMFOLD2_MODEL,
    ("mkdssp", "secondary_structure"): "mkdssp",
    ("biopython-svd", "structure_align"): "PairwiseAligner+SVDSuperimposer",
    ("tmtools", "tm_score"): "tm_align-fixed-correspondence",
}
EXPECTED_STATIC_IDENTITIES = {
    "biohub": {
        "sdk": "esm",
        "sdk_source_revision": ESM_SDK_REVISION,
        "service": "Biohub",
    },
    "local_open": {
        "sdk": "esm",
        "sdk_source_revision": ESM_SDK_REVISION,
        "service": "local_open",
        "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
        "weight_sha256": LOCAL_ESM3_WEIGHT_SHA256,
    },
    "local-proteinmpnn": {
        "source": "ProteinMPNN",
        "source_revision": PROTEINMPNN_REVISION,
        "checkpoint_sha256": PROTEINMPNN_V_48_020_SHA256,
    },
    "simplefold": {
        "source": "ml-simplefold",
        "source_revision": SIMPLEFOLD_REVISION,
        "esm2_source_revision": SIMPLEFOLD_ESM2_REVISION,
        "esm2_source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
        "esm2_artifact_sha256": SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
        "artifact_sha256": SIMPLEFOLD_ARTIFACT_SHA256,
    },
    "mkdssp": {"binary": "mkdssp", "required_version": "4.6.1"},
}


def _expected_provider_identity(provider: str) -> dict[str, object] | None:
    if provider == "biopython-svd":
        return {
            "biopython_version": importlib.metadata.version("biopython"),
            "numpy_version": importlib.metadata.version("numpy"),
        }
    if provider == "tmtools":
        return {"tmtools_version": importlib.metadata.version("tmtools")}
    return EXPECTED_STATIC_IDENTITIES.get(provider)

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
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JUNIT_BYTES:
        raise ValueError("JUnit result is not a bounded regular file")
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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def _source_attestation() -> tuple[str, bool, str]:
    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        return completed.stdout.strip()

    revision = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    source_files = git(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
    ).splitlines()
    source_digest = hashlib.sha256()
    for relative in sorted(source_files):
        path = PROJECT_ROOT / relative
        if path.is_file() and not path.is_symlink():
            source_digest.update(relative.encode() + b"\0")
            source_digest.update(path.read_bytes())
    return revision, dirty, source_digest.hexdigest()


def _environment_summary(tier_name: str) -> dict[str, object]:
    try:
        revision, dirty, source_tree_sha256 = _source_attestation()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        revision = "unavailable"
        dirty = True
        source_tree_sha256 = "unavailable"
    package_versions: dict[str, str] = {}
    for package in (
        "biopython",
        "esm",
        "numpy",
        "protein-workbench",
        "simplefold",
        "tmtools",
        "torch",
    ):
        try:
            package_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            package_versions[package] = "not-installed"
    interpreter_path = Path(sys.executable).resolve()
    interpreter_digest = hashlib.sha256()
    with interpreter_path.open("rb") as interpreter_file:
        while chunk := interpreter_file.read(1024 * 1024):
            interpreter_digest.update(chunk)
    return {
        "schema_version": 1,
        "tier": tier_name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "project_revision": revision,
        "project_dirty": dirty,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "package_versions": package_versions,
        "interpreter": str(interpreter_path),
        "interpreter_sha256": interpreter_digest.hexdigest(),
        "source_tree_sha256": source_tree_sha256,
        "isolated_roots": list(ROOT_VARIABLES),
        "historical_cache_allowed": False,
        "secrets_retained": False,
    }


def _load_and_validate_provider_evidence(
    path: Path,
    *,
    tier_name: str,
    tier: Tier,
    nonce: str,
    started_at: datetime,
    focused: bool,
) -> tuple[list[dict[str, object]], str | None]:
    try:
        if path.is_symlink() or not path.is_file():
            return [], "provider-call evidence was not a regular file"
        if path.stat().st_size > 2 * 1024 * 1024:
            return [], "provider-call evidence exceeded the size bound"
        lines = path.read_text().splitlines()
    except OSError:
        return [], "provider-call evidence was not readable"
    if not lines:
        return [], "provider-call evidence was empty"

    events: list[dict[str, object]] = []
    event_ids: set[str] = set()
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return [], "invalid provider-call evidence JSON"
        if not isinstance(event, dict):
            return [], "invalid provider-call evidence event"
        if (
            event.get("evidence_version") != 1
            or event.get("run_nonce") != nonce
            or event.get("gate") != tier_name
            or not isinstance(event.get("event_id"), str)
            or event["event_id"] in event_ids
        ):
            return [], "invalid provider-call evidence envelope"
        event_ids.add(event["event_id"])
        try:
            recorded_at = datetime.fromisoformat(str(event["recorded_at"]))
        except (KeyError, TypeError, ValueError):
            return [], "invalid provider-call evidence timestamp"
        if (
            recorded_at.tzinfo is None
            or recorded_at < started_at
            or recorded_at > datetime.now(timezone.utc)
        ):
            return [], "stale or future provider-call evidence"
        events.append(event)

    calls = [event for event in events if event.get("event_type") == "provider_call"]
    readiness_events = [
        event
        for event in events
        if event.get("event_type") == "provider_readiness"
    ]
    if len(calls) + len(readiness_events) != len(events):
        return [], "invalid provider-call evidence event type"
    for readiness in readiness_events:
        if (
            not isinstance(readiness.get("provider"), str)
            or not isinstance(readiness.get("ready"), bool)
            or not isinstance(readiness.get("provider_identity"), dict)
            or not readiness["provider_identity"]
        ):
            return [], "invalid provider readiness evidence contract"
    for call in calls:
        result = call.get("result")
        if (
            not isinstance(call.get("provider"), str)
            or not isinstance(call.get("operation"), str)
            or not isinstance(call.get("provider_identity"), dict)
            or not call["provider_identity"]
            or call.get("readiness") != "ready_at_call_boundary"
            or call.get("actual_call") is not True
            or call.get("call_count") != 1
            or "effective_seed" not in call
            or not isinstance(call.get("seed_control"), str)
            or not call["seed_control"]
            or call.get("cache_decision") != "bypassed_fresh_direct_call"
            or not isinstance(result, dict)
            or result.get("status") != "succeeded"
            or not isinstance(result.get("summary"), dict)
            or not result["summary"]
        ):
            return [], "invalid provider-call evidence contract"
        key = (str(call["provider"]), str(call["operation"]))
        if key not in tier.required_calls:
            return [], "unexpected provider call evidence"
        if call.get("model") != EXPECTED_MODELS[key]:
            return [], "provider call model identity mismatch"
        test_id = call.get("test_id")
        if not isinstance(test_id, str) or test_id not in tier.expected_test_ids:
            return [], "provider call test identity mismatch"
        expected_static = _expected_provider_identity(str(call["provider"]))
        if expected_static is not None and call["provider_identity"] != expected_static:
            return [], "provider call source identity mismatch"
    if not calls:
        return [], "no valid provider-call evidence was recorded"

    observed_calls = {
        (str(call["provider"]), str(call["operation"]))
        for call in calls
    }
    ready_providers = {
        str(event["provider"])
        for event in readiness_events
        if event.get("ready") is True
    }
    called_providers = {provider for provider, _ in observed_calls}
    missing_readiness = called_providers - ready_providers
    if missing_readiness:
        return events, (
            "missing provider readiness evidence: "
            + ", ".join(sorted(missing_readiness))
        )
    readiness_by_provider = {
        str(event["provider"]): event["provider_identity"]
        for event in readiness_events
        if event.get("ready") is True
    }
    for call in calls:
        if readiness_by_provider[str(call["provider"])] != call["provider_identity"]:
            return events, "readiness and call provider identities differ"
    observed_counts = Counter(
        (str(call["provider"]), str(call["operation"]))
        for call in calls
    )
    if any(count != 1 for count in observed_counts.values()):
        return events, "provider call count did not match the exact gate contract"
    missing = tier.required_calls - observed_calls
    if missing and not focused:
        formatted = ", ".join(
            f"{provider}:{operation}"
            for provider, operation in sorted(missing)
        )
        return events, f"missing required provider calls: {formatted}"
    return events, None


def _child_environment(tier_name: str, base: Path) -> dict[str, str]:
    """Construct a minimum tier-specific environment without ambient credentials."""
    retained = {
        "PATH",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NO_PROXY",
        "OBJC_DISABLE_INITIALIZE_FORK_SAFETY",
    }
    env = {key: os.environ[key] for key in retained if key in os.environ}
    env.update({
        "HOME": str(base / "home"),
        "TMPDIR": str(base / "tmp"),
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED", "0"),
        "PYTHONPYCACHEPREFIX": str(base / "pycache"),
    })
    Path(env["HOME"]).mkdir()
    Path(env["TMPDIR"]).mkdir()
    if tier_name == "live-provider":
        token_file = os.environ.get("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE")
        if token_file:
            env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"] = token_file
    if tier_name == "heavy-model":
        for key in (
            "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
            "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
            "HF_HOME",
            "HF_HUB_CACHE",
            "TORCH_HOME",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        if "HF_HOME" not in env and "HF_HUB_CACHE" not in env:
            env["HF_HOME"] = str(Path.home() / ".cache" / "huggingface")
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
    if tier_name == "routine" and "PROTEIN_WORKBENCH_RESOURCE_WARNING_PROBE" in os.environ:
        env["PROTEIN_WORKBENCH_RESOURCE_WARNING_PROBE"] = os.environ[
            "PROTEIN_WORKBENCH_RESOURCE_WARNING_PROBE"
        ]
    return env


def _stream_process_output(
    process: subprocess.Popen[bytes],
) -> bool:
    """Forward bounded binary chunks and detect cleanup warnings."""
    if process.stdout is None:
        raise RuntimeError("pytest output pipe was not created")
    marker = RESOURCE_CLEANUP_WARNING.encode()
    overlap = b""
    detected = False
    displayed = 0
    while chunk := process.stdout.read1(OUTPUT_CHUNK_SIZE):
        if displayed < MAX_CONSOLE_BYTES:
            retained = chunk[:MAX_CONSOLE_BYTES - displayed]
            sys.stdout.buffer.write(retained)
            sys.stdout.buffer.flush()
            displayed += len(retained)
        window = overlap + chunk
        if marker in window:
            detected = True
        overlap = window[-(len(marker) - 1):]
    return detected


def _provider_summary_completion(
    *,
    evidence_error: str | None,
    focused: bool,
    return_code: int,
    failures: int,
    skipped: int,
    tests: int,
    resource_cleanup_warning: bool,
    source_attestation_valid: bool,
) -> tuple[bool, str | None]:
    """Report completeness only when the entire provider gate can pass."""
    if evidence_error is not None:
        return False, evidence_error
    if focused:
        return False, "focused provider diagnostic"
    if skipped:
        return False, "provider pytest skipped required tests"
    if return_code != 0 or failures:
        return False, "provider pytest failed"
    if resource_cleanup_warning:
        return False, "multiprocessing resource cleanup warning"
    if tests == 0:
        return False, "no provider tests ran"
    if not source_attestation_valid:
        return False, "source attestation changed during provider execution"
    return True, None


def main() -> int:
    args = _parse_args()
    tier = TIERS[args.tier]
    if sys.prefix == sys.base_prefix:
        print(
            "BACKEND VERIFICATION RESULT: failed "
            "(run from the documented project environment)",
            flush=True,
        )
        return 2
    try:
        importlib.metadata.version("protein-workbench")
    except importlib.metadata.PackageNotFoundError:
        print(
            "BACKEND VERIFICATION RESULT: failed "
            "(protein-workbench is not installed in the project environment)",
            flush=True,
        )
        return 2
    initial_source_attestation: tuple[str, bool, str] | None = None
    if tier.requires_provider_evidence and not args.pytest_targets:
        approved_revision = os.environ.get(
            "PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION"
        )
        try:
            initial_source_attestation = _source_attestation()
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            initial_source_attestation = ("unavailable", True, "unavailable")
        if (
            not approved_revision
            or initial_source_attestation[0] != approved_revision
            or initial_source_attestation[1]
        ):
            print(
                "BACKEND VERIFICATION RESULT: failed "
                "(full provider gates require the clean approved source revision)",
                flush=True,
            )
            return 2
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
    _write_json(
        result_dir / "environment-summary.json",
        _environment_summary(args.tier),
    )
    gate_started_at = datetime.now(timezone.utc)
    gate_nonce = secrets.token_urlsafe(32)

    with tempfile.TemporaryDirectory(
        prefix=f"protein-workbench-{args.tier}-"
    ) as temporary_root:
        base = Path(temporary_root)
        env = _child_environment(args.tier, base)
        for variable in ROOT_VARIABLES:
            name = variable.removeprefix("PROTEIN_WORKBENCH_").removesuffix("_ROOT")
            root = base / name.lower()
            root.mkdir()
            env[variable] = str(root)
        env["PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED"] = "1"
        env["PROTEIN_WORKBENCH_VERIFICATION_TIER"] = args.tier
        env["PROTEIN_WORKBENCH_REAL_GATE_NONCE"] = gate_nonce
        env["PROTEIN_WORKBENCH_REAL_GATE_FRESH"] = "1"
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
        resource_cleanup_warning = False
        with subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ) as process:
            timed_out = threading.Event()

            def terminate_timed_out_process() -> None:
                timed_out.set()
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    return

                def kill_process_group() -> None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

                threading.Timer(5, kill_process_group).start()

            timer = threading.Timer(
                TIER_TIMEOUT_SECONDS,
                terminate_timed_out_process,
            )
            timer.start()
            try:
                resource_cleanup_warning = _stream_process_output(process)
                return_code = process.wait()
            finally:
                timer.cancel()
        completed = subprocess.CompletedProcess(
            command,
            return_code,
        )
        transcript_path = result_dir / "command-transcript.txt"
        display_command = [
            "$PROJECT_ENV/bin/python"
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
        if timed_out.is_set():
            print(
                "BACKEND VERIFICATION RESULT: failed (tier timeout)",
                flush=True,
            )
            return 1

        try:
            _sanitize_junit(junit_path)
        except (OSError, ValueError, ET.ParseError):
            print(
                "BACKEND VERIFICATION RESULT: failed (invalid JUnit result)",
                flush=True,
            )
            return 1
        tests, failures, skipped = _junit_counts(junit_path)
        with transcript_path.open("a") as transcript:
            transcript.write(
                f"tests={tests} failures={failures} skipped={skipped}\n"
                "resource_cleanup_warning="
                f"{str(resource_cleanup_warning).lower()}\n"
            )
        if call_evidence.exists():
            call_evidence.chmod(0o600)
        source_attestation_valid = True
        if tier.requires_provider_evidence and not args.pytest_targets:
            try:
                final_source_attestation = _source_attestation()
            except (
                OSError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ):
                final_source_attestation = (
                    "unavailable",
                    True,
                    "unavailable",
                )
            source_attestation_valid = (
                initial_source_attestation is not None
                and final_source_attestation == initial_source_attestation
                and not final_source_attestation[1]
            )
        evidence_error: str | None = None
        if tier.requires_provider_evidence and not call_evidence.exists():
            evidence_error = "no provider-call evidence was recorded"
            evidence: list[dict[str, object]] = []
        elif tier.requires_provider_evidence:
            evidence, evidence_error = _load_and_validate_provider_evidence(
                call_evidence,
                tier_name=args.tier,
                tier=tier,
                nonce=gate_nonce,
                started_at=gate_started_at,
                focused=bool(args.pytest_targets),
            )
            if evidence:
                calls = [
                    event for event in evidence
                    if event.get("event_type") == "provider_call"
                ]
                complete, incomplete_reason = _provider_summary_completion(
                    evidence_error=evidence_error,
                    focused=bool(args.pytest_targets),
                    return_code=completed.returncode,
                    failures=failures,
                    skipped=skipped,
                    tests=tests,
                    resource_cleanup_warning=resource_cleanup_warning,
                    source_attestation_valid=source_attestation_valid,
                )
                _write_json(
                    result_dir / "provider-summary.json",
                    {
                        "schema_version": 1,
                        "tier": args.tier,
                        "fresh_gate": True,
                        "historical_cache_allowed": False,
                        "complete": complete,
                        "incomplete_reason": incomplete_reason,
                        "call_count": len(calls),
                        "readiness": [
                            event for event in evidence
                            if event.get("event_type") == "provider_readiness"
                        ],
                        "calls": calls,
                    },
                )
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
        if resource_cleanup_warning:
            print(
                "BACKEND VERIFICATION RESULT: failed "
                "(multiprocessing resource cleanup warning)",
                flush=True,
            )
            return 1
        if tests == 0:
            print("BACKEND VERIFICATION RESULT: incomplete (no tests ran)", flush=True)
            return 3
        if tier.requires_provider_evidence:
            if evidence_error is not None:
                print(
                    "BACKEND VERIFICATION RESULT: incomplete "
                    f"(invalid provider-call evidence: {evidence_error})",
                    flush=True,
                )
                return 3
            if not source_attestation_valid:
                print(
                    "BACKEND VERIFICATION RESULT: failed "
                    "(source attestation changed during provider execution)",
                    flush=True,
                )
                return 1
            if args.pytest_targets:
                print(
                    "BACKEND VERIFICATION RESULT: incomplete "
                    "(focused provider diagnostics cannot satisfy a full gate)",
                    flush=True,
                )
                return 3

        print("BACKEND VERIFICATION RESULT: passed", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
