#!/usr/bin/env python3
"""Run an explicit, isolated backend verification tier."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import secrets
import select
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.provider_contract import (
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
from modules.provider_evidence import (
    _IDENTITY_KEYS,
    _CALL_DETAIL_KEYS,
    _READINESS_DETAIL_KEYS,
    _RESULT_KEYS,
    validate_provider_call_details,
)
from core.public_values import (
    sanitize_public_value,
    validate_public_scientific_value,
)
from modules.folding.simplefold_adapter import (
    simplefold_folding_artifact_sha256,
)
from modules.folding.simplefold_confidence_adapter import (
    provider_identity as simplefold_confidence_provider_identity,
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
    "TestBiohubGeneration::test_v2_all_modes_and_ten_pairs"
)
PROCESS_SUPERVISOR_FLAG = "--verification-process-supervisor"
TRUSTED_PS = "/bin/ps"
TRUSTED_GIT = "/usr/bin/git"

_SEALED_FRESH_KEYS = frozenset({
    "artifacts",
    "backend_manifest",
    "backend_manifest_sha256",
    "cache",
    "candidate_lineage",
    "effective_seeds",
    "environment",
    "fresh_run",
    "historical_cache_allowed",
    "modules",
    "ordered_node_outcomes",
    "project_id",
    "providers",
    "run_id",
    "schema_version",
    "scores",
    "secrets_retained",
    "source",
    "websocket_events",
    "workflow",
})
_BACKEND_FRESH_KEYS = frozenset({
    "artifacts",
    "blocking_reasons",
    "cache",
    "candidate_lineage",
    "created_at",
    "effective_seeds",
    "environment",
    "failures",
    "models",
    "modules",
    "node_states",
    "project_id",
    "providers",
    "run_id",
    "run_seed",
    "schema_version",
    "scores",
    "source",
    "status",
    "updated_at",
    "workflow",
})
_BACKEND_FRESH_REQUIRED_KEYS = _BACKEND_FRESH_KEYS - {
    "created_at",
    "run_seed",
    "updated_at",
}
_CALL_DETAIL_KEYS = frozenset({
    "actual_call",
    "cache_decision",
    "call_count",
    "candidate_ids",
    "effective_seed",
    "node_id",
    "parent_candidate_id",
    "provider_identity",
    "readiness",
    "requested_seed",
    "result",
    "sample_index",
    "secondary_structure_length",
    "secondary_structure_sha256",
    "seed_control",
    "seed_scope",
    *set().union(*_CALL_DETAIL_KEYS.values()),
})


def _safe_public_string(value: object, *, maximum: int = 512) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and sanitize_public_value(value) == value
    )


def _safe_identifier(value: object) -> bool:
    return (
        _safe_public_string(value, maximum=128)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]*", value) is not None
    )


def _safe_identifier_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 256
        and all(_safe_identifier(item) for item in value)
    )


def _digest_value_is_valid(value: object) -> bool:
    if isinstance(value, str):
        return re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if isinstance(value, list):
        return len(value) <= 128 and all(
            _digest_value_is_valid(item) for item in value
        )
    if isinstance(value, dict):
        return len(value) <= 128 and all(
            _safe_public_string(key)
            and _digest_value_is_valid(item)
            for key, item in value.items()
        )
    return False


def _provider_identity_values_are_valid(identity: object) -> bool:
    if not isinstance(identity, dict) or set(identity) - _IDENTITY_KEYS:
        return False
    for key, value in identity.items():
        if key.endswith("sha256"):
            if not _digest_value_is_valid(value):
                return False
        elif key.endswith("revision"):
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{40}", value) is None
            ):
                return False
        elif not _safe_public_string(value):
            return False
    return True


def _provider_summary_values_are_valid(
    operation: str,
    summary: object,
) -> bool:
    if (
        not isinstance(summary, dict)
        or operation not in _RESULT_KEYS
        or set(summary) - _RESULT_KEYS[operation]
    ):
        return False
    boolean_fields = {"has_coordinates", "has_sequence"}
    numeric_fields = {
        "coverage",
        "d0",
        "normalization_length",
        "reference_coverage",
        "rmsd",
        "score",
        "score_max",
        "score_min",
        "value",
    }
    integer_fields = {
        "aligned_residues",
        "input_sequence_length",
        "mobile_length",
        "num_steps",
        "output_bytes",
        "output_sequence_length",
        "pdb_bytes",
        "reference_length",
        "residue_count",
        "return_code",
        "score_count",
        "sequence_count",
        "sequence_length",
        "structure_count",
    }
    for key, value in summary.items():
        if key.endswith("sha256"):
            if not _digest_value_is_valid(value):
                return False
        elif key in boolean_fields:
            if not isinstance(value, bool):
                return False
        elif key == "pdb_bytes":
            scalar_is_valid = (
                not isinstance(value, bool)
                and isinstance(value, int)
                and value >= 0
            )
            list_is_valid = (
                isinstance(value, list)
                and len(value) <= 128
                and all(
                    not isinstance(item, bool)
                    and isinstance(item, int)
                    and item >= 0
                    for item in value
                )
            )
            if (
                operation == "esmfold2.fold"
                and not scalar_is_valid
                or operation == "fold_sequence"
                and not list_is_valid
                or operation not in {"esmfold2.fold", "fold_sequence"}
            ):
                return False
        elif key in integer_fields or key.endswith("_length"):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return False
        elif key in numeric_fields:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                return False
        elif key == "sequence_lengths":
            if (
                not isinstance(value, list)
                or len(value) > 128
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, int)
                    or item < 0
                    for item in value
                )
            ):
                return False
        elif key in {"score_ids", "score_values"}:
            if not isinstance(value, list) or len(value) > 128:
                return False
            if key == "score_ids" and any(
                not _safe_public_string(item) for item in value
            ):
                return False
            if key == "score_values" and any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                for item in value
            ):
                return False
        elif not _safe_public_string(value):
            return False
    return True


def _timezone_aware_iso_timestamp(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


@dataclass(frozen=True)
class Tier:
    pytest_args: tuple[str, ...]
    requires_provider_evidence: bool = False
    provider_evidence_gate: str | None = None
    provider_identity_profile: str | None = None
    required_calls: frozenset[tuple[str, str]] = frozenset()
    required_call_counts: tuple[tuple[str, str, int], ...] = ()
    expected_test_ids: frozenset[str] = frozenset()
    timeout_seconds: int = TIER_TIMEOUT_SECONDS
    termination_grace_seconds: int = 5
    requires_biohub_credential: bool = False
    requires_local_model_environment: bool = False
    requires_simplefold_environment: bool = False
    requires_fresh_bundle: bool = False

    @property
    def expected_call_counts(self) -> dict[tuple[str, str], int]:
        """Return one source of truth for exact provider multiplicities."""
        if self.required_call_counts:
            return {
                (provider, operation): count
                for provider, operation, count in self.required_call_counts
            }
        return {key: 1 for key in self.required_calls}


FRESH_CALL_NODE_COUNTS = (
    ("local_open", "esm3.generate_sequence", "esm3_gen", 10),
    ("local_open", "esm3.generate_structure", "esm3_gen", 10),
    ("biohub", "esmfold2.fold", "fold_seq", 10),
    ("biohub", "esmfold2.fold", "final_fold", 15),
    ("local-proteinmpnn", "design_sequences", "mpnn_0", 3),
    ("mkdssp", "secondary_structure", "compute_ss", 1),
    ("biopython-svd", "structure_align", "align_3gb1", 10),
    ("biopython-svd", "structure_align", "align_pw", 10),
    ("tmtools", "tm_score", "tm_3gb1", 10),
    ("tmtools", "tm_score", "tm_esm3", 10),
)
FRESH_REQUIRED_CALL_COUNTS = Counter()
for _provider, _operation, _node_id, _count in FRESH_CALL_NODE_COUNTS:
    FRESH_REQUIRED_CALL_COUNTS[(_provider, _operation)] += _count
FRESH_CALL_NODE_COUNT_MAP = Counter({
    (provider, operation, node_id): count
    for provider, operation, node_id, count in FRESH_CALL_NODE_COUNTS
})
EXPECTED_SEED_CONTROLS = {
    ("biohub", "esm3.generate_sequence"): "unsupported_by_provider",
    ("biohub", "esm3.generate_structure"): "unsupported_by_provider",
    ("biohub", "esmfold2.fold"): "unsupported_by_provider",
    ("biopython-svd", "structure_align"): "deterministic_no_rng",
    ("local-proteinmpnn", "design_sequences"): "provider_request_seed",
    ("local-proteinmpnn", "score_sequence"): "fixed_scoring_seed",
    ("local_open", "esm3.generate_sequence"): "torch_local",
    ("local_open", "esm3.generate_structure"): "torch_local",
    ("mkdssp", "secondary_structure"): "deterministic_no_rng",
    ("simplefold", "evaluate_structure"): (
        "deterministic_existing_coordinates"
    ),
    ("simplefold", "fold_sequence"): "torch_local",
    ("tmtools", "tm_score"): "deterministic_no_rng",
}


TIERS = {
    "routine": Tier((
        "tests",
        "-m",
        "not acceptance and not installed_package "
        "and not deterministic_acceptance "
        "and not live_provider and not local_provider "
        "and not slow and not scientific_repro "
        "and not repair_findings",
    )),
    "examples-v2": Tier((
        "tests/test_repository_examples_v2.py",
    )),
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
    "installed-package": Tier((
        "tests/test_installable_backend.py",
        "-m",
        "installed_package",
    )),
    "scientific-repro": Tier((
        (
            "tests/test_esm3_v2.py::"
            "test_adapter_preserves_every_representable_prompt_track_and_symbol"
        ),
    )),
    "repair-findings": Tier((
        "tests/deterministic_acceptance/test_review_findings.py",
        "-m",
        "repair_findings",
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
    "local-esm3-heavy-model": Tier((
        "tests/acceptance/test_local_esm3.py::"
        "test_local_esm3_all_generation_modes",
        "-m",
        "local_provider and slow",
    ),
        requires_provider_evidence=True,
        provider_evidence_gate="heavy-model",
        required_call_counts=(
            ("local_open", "esm3.generate_sequence", 2),
            ("local_open", "esm3.generate_structure", 2),
        ),
        expected_test_ids=frozenset({
            "tests/acceptance/test_local_esm3.py::"
            "test_local_esm3_all_generation_modes",
        }),
        requires_local_model_environment=True,
    ),
    "local-esmfold2-v2-contract": Tier((
        "tests/acceptance/test_esmfold2_v2.py::"
        "test_local_esmfold2_v2_source_contract_and_native_result",
        "tests/test_folding_v2.py::"
        "test_native_plddt_is_statically_scaled_and_masks_invalid_tokens",
        "tests/test_folding_v2.py::"
        "test_remote_and_local_provider_native_results_normalize_identically",
        "tests/test_folding_v2.py::"
        "test_selected_binding_folds_without_fallback_and_publishes_exact_lineage"
        "[local]",
        "tests/test_folding_v2.py::"
        "test_remote_and_local_bindings_pass_shared_contract_test_kit",
        "-m",
        "not live_provider and not local_provider",
    )),
    "simplefold-v2-heavy-model": Tier((
        "tests/acceptance/test_simplefold_v2.py::"
        "test_simplefold_v2_folds_3gb1_through_exact_binding",
        "-m",
        "local_provider and slow",
    ),
        requires_provider_evidence=True,
        provider_evidence_gate="heavy-model",
        provider_identity_profile="simplefold-v2-folding",
        required_call_counts=(
            ("simplefold", "fold_sequence", 1),
        ),
        expected_test_ids=frozenset({
            "tests/acceptance/test_simplefold_v2.py::"
            "test_simplefold_v2_folds_3gb1_through_exact_binding",
        }),
        requires_local_model_environment=True,
        requires_simplefold_environment=True,
    ),
    "simplefold-confidence-v2-heavy-model": Tier((
        "tests/acceptance/test_simplefold_confidence_v2.py::"
        "test_simplefold_confidence_v2_evaluates_3gb1_exact_assets_without_refold",
        "-m",
        "local_provider and slow",
    ),
        requires_provider_evidence=True,
        provider_evidence_gate="heavy-model",
        provider_identity_profile="simplefold-v2-confidence",
        required_call_counts=(
            ("simplefold", "evaluate_structure", 1),
        ),
        expected_test_ids=frozenset({
            "tests/acceptance/test_simplefold_confidence_v2.py::"
            "test_simplefold_confidence_v2_evaluates_3gb1_exact_assets_without_refold",
        }),
        requires_local_model_environment=True,
        requires_simplefold_environment=True,
    ),
    "proteinmpnn-scoring-v2-heavy-model": Tier((
        "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
        "test_proteinmpnn_v2_scoring_publishes_exact_native_observation",
        "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
        "test_proteinmpnn_v2_sibling_design_remains_exact_and_complete",
        "-m",
        "local_provider and slow",
    ),
        requires_provider_evidence=True,
        provider_evidence_gate="heavy-model",
        provider_identity_profile="proteinmpnn-v2",
        required_call_counts=(
            ("local-proteinmpnn", "score_sequence", 1),
            ("local-proteinmpnn", "design_sequences", 1),
        ),
        expected_test_ids=frozenset({
            "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
            "test_proteinmpnn_v2_scoring_publishes_exact_native_observation",
            "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
            "test_proteinmpnn_v2_sibling_design_remains_exact_and_complete",
        }),
        requires_local_model_environment=True,
    ),
    "soluprot-v2-local-model": Tier((
        "tests/acceptance/test_soluprot_v2.py",
        "-m",
        "acceptance and local_provider",
    )),
    "protein-sol-v2-local-model": Tier((
        "tests/acceptance/test_protein_sol_v2.py",
        "-m",
        "acceptance and local_provider",
    )),
    "heavy-model": Tier((
        "tests/acceptance/test_local_esm3.py::test_local_esm3_all_generation_modes",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_design_3gb1",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_score_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_fold_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_evaluate_3gb1",
        "-m",
        "local_provider and slow",
    ), requires_provider_evidence=True, required_call_counts=(
        ("local_open", "esm3.generate_sequence", 2),
        ("local_open", "esm3.generate_structure", 2),
        ("local-proteinmpnn", "design_sequences", 1),
        ("local-proteinmpnn", "score_sequence", 1),
        ("simplefold", "fold_sequence", 1),
        ("simplefold", "evaluate_structure", 1),
    ), expected_test_ids=frozenset({
        "tests/acceptance/test_local_esm3.py::test_local_esm3_all_generation_modes",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_design_3gb1",
        "tests/acceptance/test_proteinmpnn_design.py::TestProteinMPNNDesign::test_score_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_fold_3gb1",
        "tests/acceptance/test_simplefold.py::TestSimpleFold::test_evaluate_3gb1",
    }),
        requires_local_model_environment=True,
        requires_simplefold_environment=True,
    ),
    "live-provider": Tier((
        LIVE_ESM3_TEST,
        "tests/acceptance/test_biohub_folding.py::TestBiohubFolding::test_fold_3gb1[False-False]",
        "-m",
        "live_provider",
    ), requires_provider_evidence=True, required_call_counts=(
        ("biohub", "esm3.generate_sequence", 11),
        ("biohub", "esm3.generate_structure", 11),
        ("biohub", "esmfold2.fold", 1),
    ), expected_test_ids=frozenset({
        LIVE_ESM3_TEST,
        "tests/acceptance/test_biohub_folding.py::TestBiohubFolding::test_fold_3gb1[False-False]",
    }), requires_biohub_credential=True),
    "remote-esmfold2-v2": Tier((
        "tests/acceptance/test_esmfold2_v2.py::"
        "test_remote_esmfold2_v2_folds_3gb1_through_exact_binding",
        "-m",
        "live_provider",
    ),
        requires_provider_evidence=True,
        provider_evidence_gate="live-provider",
        required_call_counts=(
            ("biohub", "esmfold2.fold", 1),
        ),
        expected_test_ids=frozenset({
            "tests/acceptance/test_esmfold2_v2.py::"
            "test_remote_esmfold2_v2_folds_3gb1_through_exact_binding",
        }),
        requires_biohub_credential=True,
    ),
    "fresh-remote-3gb1": Tier((
        "tests/fresh_remote_acceptance/test_fresh_remote_3gb1.py::"
        "test_fresh_remote_real_canonical_3gb1",
        "-m",
        "fresh_remote_real",
    ), requires_provider_evidence=True, required_call_counts=tuple(
        (provider, operation, count)
        for (provider, operation), count
        in sorted(FRESH_REQUIRED_CALL_COUNTS.items())
    ), expected_test_ids=frozenset({
        "tests/fresh_remote_acceptance/test_fresh_remote_3gb1.py::"
        "test_fresh_remote_real_canonical_3gb1",
    }),
        timeout_seconds=3 * 60 * 60,
        termination_grace_seconds=30,
        requires_biohub_credential=True,
        requires_local_model_environment=True,
        requires_fresh_bundle=True,
    ),
}

EXPECTED_MODELS = {
    ("local_open", "esm3.generate_sequence"): "esm3_sm_open_v1",
    ("local_open", "esm3.generate_structure"): "esm3_sm_open_v1",
    ("local-proteinmpnn", "design_sequences"): "v_48_020",
    ("local-proteinmpnn", "score_sequence"): "v_48_020",
    ("simplefold", "fold_sequence"): "simplefold_100M",
    ("simplefold", "evaluate_structure"): "simplefold_360M",
    ("biohub", "esm3.generate_sequence"): BIOHUB_ESM3_MODEL,
    ("biohub", "esm3.generate_structure"): BIOHUB_ESM3_MODEL,
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


def _expected_provider_identity(
    provider: str,
    *,
    profile: str | None = None,
) -> dict[str, object] | None:
    if provider == "simplefold" and profile == "simplefold-v2-folding":
        return {
            **EXPECTED_STATIC_IDENTITIES["simplefold"],
            "artifact_sha256": simplefold_folding_artifact_sha256(),
        }
    if provider == "simplefold" and profile == "simplefold-v2-confidence":
        return simplefold_confidence_provider_identity()
    if provider == "biopython-svd":
        return {
            "biopython_version": importlib.metadata.version("biopython"),
            "numpy_version": importlib.metadata.version("numpy"),
        }
    if provider == "tmtools":
        return {"tmtools_version": importlib.metadata.version("tmtools")}
    return EXPECTED_STATIC_IDENTITIES.get(provider)


def _expected_seed_control(
    key: tuple[str, str],
    *,
    profile: str | None,
) -> str | None:
    if (
        profile == "proteinmpnn-v2"
        and key == ("local-proteinmpnn", "design_sequences")
    ):
        return "torch_local"
    return EXPECTED_SEED_CONTROLS.get(key)


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


def _process_group_members(process_group: int) -> set[int]:
    """Return current members while the supervisor keeps the PGID alive."""
    completed = subprocess.run(
        [TRUSTED_PS, "-axo", "pid=,pgid="],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        start_new_session=True,
    )
    members: set[int] = set()
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pid, pgid = (int(field) for field in fields)
        except ValueError:
            continue
        if pgid == process_group:
            members.add(pid)
    return members


def _write_descriptor(descriptor: int, payload: bytes) -> None:
    written = 0
    while written < len(payload):
        count = os.write(descriptor, payload[written:])
        if count <= 0:
            raise OSError("descriptor write made no progress")
        written += count


def _finish_supervisor_control(
    descriptor: int,
    *,
    normal_child_done: bool,
    timed_out: bool,
) -> bool:
    """Release normal runs, but retain timeout control until PGID reap."""
    if timed_out:
        return True
    try:
        if normal_child_done:
            _write_descriptor(descriptor, b"R")
    finally:
        os.close(descriptor)
    return False


def supervise_verification_process_group(
    command: list[str],
    *,
    control_descriptor: int,
    status_descriptor: int,
) -> int:
    """Hold the verification PGID until the parent explicitly releases it."""
    if (
        not command
        or control_descriptor < 3
        or status_descriptor < 3
        or os.getpid() != os.getpgrp()
    ):
        return 2
    termination_requested = threading.Event()
    release_requested = threading.Event()
    lifecycle_lock = threading.Lock()

    def retain_group_leader(
        signum: int,
        frame: object,
    ) -> None:
        del signum, frame
        termination_requested.set()

    signal.signal(signal.SIGTERM, retain_group_leader)

    def escalate_parent_loss() -> None:
        with lifecycle_lock:
            termination_requested.set()
            try:
                os.killpg(os.getpgrp(), signal.SIGTERM)
            except ProcessLookupError:
                return

            def force_group_exit() -> None:
                try:
                    os.killpg(os.getpgrp(), signal.SIGKILL)
                except ProcessLookupError:
                    pass

            escalation = threading.Timer(5, force_group_exit)
            escalation.daemon = True
            escalation.start()

    def watch_parent() -> None:
        try:
            control = os.read(control_descriptor, 1)
        except OSError:
            control = b""
        finally:
            os.close(control_descriptor)
        if control == b"R":
            release_requested.set()
            return
        escalate_parent_loss()

    parent_watch = threading.Thread(target=watch_parent, daemon=True)
    parent_watch.start()
    _write_descriptor(status_descriptor, b"READY\n")
    with lifecycle_lock:
        if termination_requested.is_set():
            while True:
                signal.pause()
        child = subprocess.Popen(command)
    return_code = child.wait()

    supervisor_pid = os.getpid()
    process_group = os.getpgrp()
    deadline = time.monotonic() + 5
    signalled: set[int] = set()
    while True:
        try:
            members = _process_group_members(process_group) - {
                supervisor_pid
            }
        except (OSError, subprocess.SubprocessError):
            escalate_parent_loss()
            while True:
                signal.pause()
        if termination_requested.is_set():
            while True:
                signal.pause()
        if not members:
            break
        selected_signal = (
            signal.SIGTERM
            if time.monotonic() < deadline
            else signal.SIGKILL
        )
        for pid in sorted(members):
            if selected_signal == signal.SIGTERM and pid in signalled:
                continue
            try:
                os.kill(pid, selected_signal)
            except ProcessLookupError:
                continue
            signalled.add(pid)
        time.sleep(0.05)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    devnull_descriptor = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_descriptor, 1)
        os.dup2(devnull_descriptor, 2)
    finally:
        if devnull_descriptor > 2:
            os.close(devnull_descriptor)
    _write_descriptor(
        status_descriptor,
        f"DONE:{return_code}\n".encode(),
    )
    os.close(status_descriptor)

    while not release_requested.wait(timeout=0.1):
        if termination_requested.is_set():
            while True:
                signal.pause()
    if termination_requested.is_set():
        while True:
            signal.pause()
    return return_code


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


def _write_private_file_once(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> None:
    """Publish one parent-owned evidence file without following links."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("evidence publication made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(mode)


def _write_json_once(path: Path, payload: object) -> None:
    _write_private_file_once(
        path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
    )


def _publish_private_file(
    source: Path,
    destination: Path,
    *,
    maximum_bytes: int,
) -> None:
    payload = _read_stable_private_file(
        source,
        maximum_bytes=maximum_bytes,
    )
    _write_private_file_once(destination, payload)


def _publish_provider_events(
    destination: Path,
    events: list[dict[str, object]],
) -> None:
    """Retain only events that the parent verifier already validated."""
    payload = "".join(
        json.dumps(event, sort_keys=True) + "\n"
        for event in events
    ).encode()
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("validated provider evidence exceeded the size bound")
    _write_private_file_once(destination, payload)


def _publish_fresh_evidence(
    staging_root: Path,
    result_dir: Path,
) -> None:
    """Copy the child-produced bundle into parent-owned retained storage."""
    if staging_root.is_symlink() or not staging_root.is_dir():
        raise ValueError("fresh evidence staging root was unsafe")
    root_entries = {path.name: path for path in staging_root.iterdir()}
    if set(root_entries) != {
        "artifact-checksums.sha256",
        "artifacts",
        "sealed-manifest.json",
    }:
        raise ValueError("fresh evidence staging inventory was incomplete")
    artifact_source = root_entries["artifacts"]
    if artifact_source.is_symlink() or not artifact_source.is_dir():
        raise ValueError("fresh evidence artifact staging was unsafe")
    source_artifacts = sorted(artifact_source.iterdir())
    if (
        len(source_artifacts) != 15
        or any(
            artifact.is_symlink()
            or not artifact.is_file()
            or artifact.suffix != ".pdb"
            for artifact in source_artifacts
        )
    ):
        raise ValueError("fresh evidence artifact staging was incomplete")
    artifact_destination = result_dir / "artifacts"
    artifact_destination.mkdir(mode=0o700)
    artifact_destination.chmod(0o700)
    for artifact in source_artifacts:
        _publish_private_file(
            artifact,
            artifact_destination / artifact.name,
            maximum_bytes=16 * 1024 * 1024,
        )
    for name, maximum_bytes in (
        ("artifact-checksums.sha256", 64 * 1024),
        ("sealed-manifest.json", 16 * 1024 * 1024),
    ):
        _publish_private_file(
            root_entries[name],
            result_dir / name,
            maximum_bytes=maximum_bytes,
        )


def _publish_validated_fresh_bundle(
    quarantine_root: Path,
    result_dir: Path,
) -> None:
    """Publish only a parent-validated, sealed fresh bundle."""
    artifact_source = quarantine_root / "artifacts"
    artifact_destination = result_dir / "artifacts"
    artifact_destination.mkdir(mode=0o700)
    artifact_destination.chmod(0o700)
    for artifact in sorted(artifact_source.iterdir()):
        _publish_private_file(
            artifact,
            artifact_destination / artifact.name,
            maximum_bytes=16 * 1024 * 1024,
        )
    for name, maximum_bytes in (
        ("artifact-checksums.sha256", 64 * 1024),
        ("sealed-manifest.json", 16 * 1024 * 1024),
        ("bundle-checksums.sha256", 64 * 1024),
    ):
        _publish_private_file(
            quarantine_root / name,
            result_dir / name,
            maximum_bytes=maximum_bytes,
        )


def _source_attestation() -> tuple[str, bool, str]:
    def git(*args: str) -> str:
        completed = subprocess.run(
            [TRUSTED_GIT, *args],
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


def validate_provider_evidence(
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
    envelope_keys = {
        "evidence_version",
        "event_id",
        "event_type",
        "gate",
        "recorded_at",
        "run_nonce",
        "test_id",
    }
    readiness_keys = envelope_keys | {
        "details",
        "provider",
        "provider_identity",
        "ready",
    }
    call_keys = envelope_keys | {
        "actual_call",
        "cache_decision",
        "call_count",
        "effective_seed",
        "model",
        "operation",
        "provider",
        "provider_identity",
        "readiness",
        "result",
        "seed_control",
    }
    call_lineage_keys = {
        "candidate_id",
        "candidate_ids",
        "node_id",
        "parent_candidate_id",
        "run_id",
    }
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
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
                r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                event["event_id"],
            )
            is None
            or event["event_id"] in event_ids
            or not _safe_public_string(event.get("test_id"))
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
        event_type = event.get("event_type")
        if event_type == "provider_readiness":
            readiness_provider = event.get("provider")
            expected_identity = (
                _expected_provider_identity(
                    readiness_provider,
                    profile=tier.provider_identity_profile,
                )
                if isinstance(readiness_provider, str)
                else None
            )
            if (
                set(event) != readiness_keys
                or not _safe_identifier(readiness_provider)
                or readiness_provider
                not in {
                    provider
                    for provider, _operation in tier.expected_call_counts
                }
                or event.get("test_id") not in tier.expected_test_ids
                or not _provider_identity_values_are_valid(
                    event.get("provider_identity")
                )
                or expected_identity is None
                or event.get("provider_identity") != expected_identity
                or not isinstance(event.get("details"), dict)
                or set(event["details"]) - _READINESS_DETAIL_KEYS
                or any(
                    not isinstance(value, bool)
                    for value in event["details"].values()
                )
                or not isinstance(event.get("ready"), bool)
                or (not focused and event.get("ready") is not True)
            ):
                return [], "invalid provider readiness evidence schema"
        elif event_type == "provider_call":
            key = (str(event.get("provider")), str(event.get("operation")))
            if (
                not call_keys.issubset(event)
                or set(event) - call_keys - call_lineage_keys
                or not _provider_identity_values_are_valid(
                    event.get("provider_identity")
                )
                or event.get("seed_control")
                != _expected_seed_control(
                    key,
                    profile=tier.provider_identity_profile,
                )
                or (
                    event.get("effective_seed") is not None
                    and (
                        isinstance(event["effective_seed"], bool)
                        or not isinstance(event["effective_seed"], int)
                    )
                )
            ):
                return [], "invalid provider call evidence schema"
            result = event.get("result")
            operation = event.get("operation")
            if (
                not isinstance(result, dict)
                or set(result) != {"status", "summary"}
                or not isinstance(operation, str)
                or not _provider_summary_values_are_valid(
                    operation,
                    result.get("summary"),
                )
            ):
                return [], "invalid provider call result schema"
            for lineage_key in call_lineage_keys:
                if lineage_key not in event:
                    continue
                lineage_value = event[lineage_key]
                if lineage_key == "candidate_ids":
                    if (
                        not isinstance(lineage_value, list)
                        or len(lineage_value) > 128
                        or any(
                            not _safe_public_string(item)
                            for item in lineage_value
                        )
                    ):
                        return [], "invalid provider call lineage schema"
                elif not _safe_public_string(lineage_value):
                    return [], "invalid provider call lineage schema"
        else:
            return [], "invalid provider-call evidence event type"
        events.append({
            key: event[key]
            for key in (
                readiness_keys
                if event_type == "provider_readiness"
                else call_keys | (set(event) & call_lineage_keys)
            )
        })

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
        if key not in tier.expected_call_counts:
            return [], "unexpected provider call evidence"
        expected_model = (
            "simplefold_confidence_1.6B"
            if (
                tier.provider_identity_profile
                == "simplefold-v2-confidence"
                and key == ("simplefold", "evaluate_structure")
            )
            else EXPECTED_MODELS[key]
        )
        if call.get("model") != expected_model:
            return [], "provider call model identity mismatch"
        test_id = call.get("test_id")
        if not isinstance(test_id, str) or test_id not in tier.expected_test_ids:
            return [], "provider call test identity mismatch"
        expected_static = _expected_provider_identity(
            str(call["provider"]),
            profile=tier.provider_identity_profile,
        )
        if expected_static is not None and call["provider_identity"] != expected_static:
            return [], "provider call source identity mismatch"
    if not calls:
        return [], "no valid provider-call evidence was recorded"
    expected_readiness_providers = {
        provider for provider, _operation in tier.expected_call_counts
    }
    observed_readiness_providers = [
        str(event["provider"]) for event in readiness_events
    ]
    if (
        len(observed_readiness_providers)
        != len(set(observed_readiness_providers))
        or set(observed_readiness_providers)
        != expected_readiness_providers
    ):
        return [], "provider readiness inventory mismatch"

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
    required_counts = tier.expected_call_counts
    for key, observed in sorted(observed_counts.items()):
        expected = required_counts[key]
        if observed != expected:
            provider, operation = key
            return events, (
                "provider call count mismatch: "
                f"{provider}:{operation} expected {expected}, "
                f"observed {observed}"
            )
    missing = set(required_counts) - observed_calls
    if missing and not focused:
        formatted = ", ".join(
            f"{provider}:{operation}"
            for provider, operation in sorted(missing)
        )
        return events, f"missing required provider calls: {formatted}"
    return events, None


def _child_environment(
    tier_name: str,
    tier: Tier,
    base: Path,
) -> dict[str, str]:
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
    if tier.requires_biohub_credential:
        token_file = os.environ.get("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE")
        if token_file:
            env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"] = token_file
    if tier.requires_local_model_environment:
        for key in (
            "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
            "HF_HOME",
            "HF_HUB_CACHE",
            "TORCH_HOME",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        if tier.requires_simplefold_environment:
            for key in (
                "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
                "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
                "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
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


def _read_stable_private_file(
    path: Path,
    *,
    maximum_bytes: int,
) -> bytes:
    """Read one owner-only, unlinked, stable regular evidence file."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o077
            or before.st_size > maximum_bytes
        ):
            raise ValueError("evidence file metadata is unsafe")
        chunks: list[bytes] = []
        retained = 0
        while chunk := os.read(descriptor, min(1024 * 1024, maximum_bytes + 1)):
            retained += len(chunk)
            if retained > maximum_bytes:
                raise ValueError("evidence file exceeds its size bound")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        for field_name in (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_nlink",
        ):
            if getattr(before, field_name) != getattr(after, field_name):
                raise ValueError("evidence file changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _fresh_manifest_schema_error(sealed: object) -> str | None:
    """Reject any retained field outside the canonical public schema."""
    if not isinstance(sealed, dict) or set(sealed) != _SEALED_FRESH_KEYS:
        return "sealed manifest schema was not closed"
    backend = sealed.get("backend_manifest")
    if (
        not isinstance(backend, dict)
        or not _BACKEND_FRESH_REQUIRED_KEYS.issubset(backend)
        or set(backend) - _BACKEND_FRESH_KEYS
    ):
        return "sealed backend manifest schema was not closed"
    backend_source = backend.get("source")
    backend_workflow = backend.get("workflow")
    backend_environment = backend.get("environment")
    backend_providers = backend.get("providers")
    sealed_providers = sealed.get("providers")
    if (
        not isinstance(backend_source, dict)
        or set(backend_source) != {"revision", "dirty"}
        or not isinstance(backend_workflow, dict)
        or set(backend_workflow) != {"sha256"}
        or not isinstance(backend_environment, dict)
        or set(backend_environment)
        != {"implementation", "platform", "python"}
        or backend.get("failures") != []
        or backend.get("blocking_reasons") != []
        or not isinstance(backend_providers, dict)
        or set(backend_providers) != {"calls", "readiness"}
        or not isinstance(sealed_providers, dict)
        or set(sealed_providers)
        != {"run_call_attempts", "validated_real_events"}
    ):
        return "sealed backend manifest shape was not canonical"
    if (
        backend.get("schema_version") != 1
        or backend.get("status") != "completed"
        or backend.get("project_id") != sealed.get("project_id")
        or backend.get("run_id") != sealed.get("run_id")
        or not _safe_identifier(backend.get("project_id"))
        or not _safe_identifier(backend.get("run_id"))
        or not isinstance(backend_workflow.get("sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}",
            backend_workflow["sha256"],
        )
        is None
    ):
        return "sealed backend root values were invalid"
    for timestamp_field in ("created_at", "updated_at"):
        if (
            timestamp_field in backend
            and not _timezone_aware_iso_timestamp(backend[timestamp_field])
        ):
            return "sealed backend timestamp was invalid"
    if "run_seed" in backend and (
        isinstance(backend["run_seed"], bool)
        or not isinstance(backend["run_seed"], int)
    ):
        return "sealed backend run seed was invalid"
    duplicated_fields = {
        "workflow": "workflow",
        "modules": "modules",
        "environment": "environment",
        "effective_seeds": "effective_seeds",
        "cache": "cache",
        "ordered_node_outcomes": "node_states",
        "candidate_lineage": "candidate_lineage",
        "scores": "scores",
    }
    if any(
        sealed.get(sealed_key) != backend.get(backend_key)
        for sealed_key, backend_key in duplicated_fields.items()
    ):
        return "sealed manifest duplicated facts differed from backend"
    if sealed_providers.get("run_call_attempts") != backend_providers.get(
        "calls"
    ):
        return "sealed provider call facts differed from backend"

    record_schemas = (
        ("modules", {"module_id", "node_id", "version"}),
        (
            "cache",
            {"cache_key", "consumer", "node_id", "outcome", "published"},
        ),
        (
            "candidate_lineage",
            {"candidate_id", "node_id", "output_port", "parent_ids"},
        ),
        (
            "scores",
            {
                "details",
                "node_id",
                "output_port",
                "score_id",
                "subjects",
                "value",
            },
        ),
        (
            "artifacts",
            {
                "candidate_id",
                "node_id",
                "output_port",
                "reference",
                "sha256",
                "size",
            },
        ),
    )
    for field, expected_keys in record_schemas:
        records = backend.get(field)
        if (
            not isinstance(records, list)
            or any(
                not isinstance(record, dict)
                or set(record) != expected_keys
                for record in records
            )
        ):
            return f"sealed backend {field} schema was not closed"
    models = backend.get("models")
    if (
        not isinstance(models, list)
        or any(
            not isinstance(model, dict)
            or set(model) != {"identity", "module_id", "node_id", "version"}
            or not all(
                _safe_public_string(model[field])
                for field in ("identity", "module_id", "node_id", "version")
            )
            for model in models
        )
    ):
        return "sealed backend models schema was not closed"
    node_states = backend.get("node_states")
    if (
        not isinstance(node_states, list)
        or any(
            not isinstance(node_state, dict)
            or set(node_state)
            not in (
                {"node_id", "old_state", "sequence", "state"},
                {"node_id", "old_state", "sequence", "state", "timestamp"},
            )
            or (
                "timestamp" in node_state
                and not _timezone_aware_iso_timestamp(
                    node_state["timestamp"]
                )
            )
            for node_state in node_states
        )
    ):
        return "sealed backend node_states schema was not closed"
    if any(
        not isinstance(cache.get("consumer"), dict)
        or set(cache["consumer"]) != {"node_id", "project_id", "run_id"}
        for cache in backend["cache"]
    ):
        return "sealed backend cache consumer schema was not closed"
    if (
        any(
            not _safe_public_string(backend_environment[field])
            for field in ("implementation", "platform", "python")
        )
        or not isinstance(backend.get("effective_seeds"), dict)
        or any(
            not _safe_identifier(node_id)
            or isinstance(seed, bool)
            or not isinstance(seed, int)
            for node_id, seed in backend["effective_seeds"].items()
        )
        or any(
            not all(
                _safe_identifier(module[field])
                for field in ("module_id", "node_id", "version")
            )
            for module in backend["modules"]
        )
    ):
        return "sealed backend identity values were invalid"
    allowed_states = {
        "blocked",
        "cancelled",
        "completed",
        "failed",
        "idle",
        "queued",
        "running",
    }
    for node_state in backend["node_states"]:
        if (
            not _safe_identifier(node_state["node_id"])
            or isinstance(node_state["sequence"], bool)
            or not isinstance(node_state["sequence"], int)
            or node_state["sequence"] < 1
            or node_state["old_state"] not in allowed_states
            or node_state["state"] not in allowed_states
        ):
            return "sealed backend Node state values were invalid"
    for cache in backend["cache"]:
        consumer = cache["consumer"]
        if (
            not _safe_identifier(cache["cache_key"])
            or not _safe_identifier(cache["node_id"])
            or cache["outcome"] not in {"bypass", "hit", "miss"}
            or not isinstance(cache["published"], bool)
            or not all(
                _safe_identifier(consumer[field])
                for field in ("node_id", "project_id", "run_id")
            )
        ):
            return "sealed backend Cache values were invalid"
    for lineage in backend["candidate_lineage"]:
        if (
            not all(
                _safe_identifier(lineage[field])
                for field in ("candidate_id", "node_id", "output_port")
            )
            or not _safe_identifier_list(lineage["parent_ids"])
        ):
            return "sealed backend lineage values were invalid"
    for score in backend["scores"]:
        if (
            not all(
                _safe_identifier(score[field])
                for field in ("node_id", "output_port", "score_id")
            )
            or isinstance(score["value"], bool)
            or not isinstance(score["value"], (int, float))
            or not math.isfinite(float(score["value"]))
            or not _safe_identifier_list(score["subjects"])
        ):
            return "sealed backend score values were invalid"
    for artifact in backend["artifacts"]:
        if (
            not all(
                _safe_identifier(artifact[field])
                for field in ("candidate_id", "node_id", "output_port")
            )
            or not _safe_public_string(artifact["reference"])
            or Path(artifact["reference"]).is_absolute()
            or ".." in Path(artifact["reference"]).parts
            or not isinstance(artifact["size"], int)
            or isinstance(artifact["size"], bool)
            or artifact["size"] <= 0
            or not isinstance(artifact["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
        ):
            return "sealed backend artifact values were invalid"
    try:
        for score in backend["scores"]:
            if not isinstance(score.get("details"), dict):
                return "sealed backend score details were invalid"
            validate_public_scientific_value(score["details"])
    except ValueError:
        return "sealed backend score details were invalid"

    readiness = backend_providers.get("readiness")
    calls = backend_providers.get("calls")
    if (
        not isinstance(readiness, list)
        or any(
            not isinstance(fact, dict)
            or set(fact)
            != {
                "details",
                "provider",
                "provider_identity",
                "ready",
                "source",
                "status",
            }
            or not isinstance(fact.get("details"), dict)
            or set(fact["details"])
            - (_READINESS_DETAIL_KEYS | {"access_configured"})
            or any(
                not isinstance(value, bool)
                for value in fact["details"].values()
            )
            or not _provider_identity_values_are_valid(
                fact.get("provider_identity")
            )
            or not isinstance(fact.get("source"), dict)
            or set(fact["source"]) != {"kind", "module_ids", "node_ids"}
            for fact in readiness
        )
        or not isinstance(calls, list)
    ):
        return "sealed backend provider readiness schema was not closed"
    if any(
        not _safe_identifier(fact["provider"])
        or fact["ready"] is not True
        or fact["status"] != "ready"
        or fact["source"]["kind"] != "workflow_required_boundary"
        or not _safe_identifier_list(fact["source"]["module_ids"])
        or not _safe_identifier_list(fact["source"]["node_ids"])
        for fact in readiness
    ):
        return "sealed backend provider readiness values were invalid"
    for call in calls:
        if (
            not isinstance(call, dict)
            or set(call) != {"details", "model", "operation", "provider"}
            or not isinstance(call.get("details"), dict)
            or set(call["details"]) - _CALL_DETAIL_KEYS
        ):
            return "sealed backend provider call schema was not closed"
        if not all(
            _safe_public_string(call[field], maximum=128)
            for field in ("model", "operation", "provider")
        ):
            return "sealed backend provider call values were invalid"
        details = call["details"]
        for detail_key in (
            "candidate_id",
            "mobile_candidate_id",
            "node_id",
            "parent_candidate_id",
            "reference_input",
            "reference_candidate_id",
            "score_id",
            "mobile_input",
        ):
            detail_value = details.get(detail_key)
            if detail_value is not None and not _safe_identifier(detail_value):
                return "sealed backend provider call values were invalid"
        if "candidate_ids" in details and not _safe_identifier_list(
            details["candidate_ids"]
        ):
            return "sealed backend provider call values were invalid"
        for detail_key in ("requested_seed", "sample_index"):
            if detail_key in details and (
                isinstance(details[detail_key], bool)
                or not isinstance(details[detail_key], int)
                or details[detail_key] < 0
            ):
                return "sealed backend provider call values were invalid"
        if (
            "seed_scope" in details
            and details["seed_scope"] != "per_sample_track"
        ):
            return "sealed backend provider call values were invalid"
        if "secondary_structure_length" in details and (
            isinstance(details["secondary_structure_length"], bool)
            or not isinstance(details["secondary_structure_length"], int)
            or details["secondary_structure_length"] < 0
        ):
            return "sealed backend provider call values were invalid"
        if "secondary_structure_sha256" in details and not _digest_value_is_valid(
            details["secondary_structure_sha256"]
        ):
            return "sealed backend provider call values were invalid"
        if "actual_call" in details and details["actual_call"] is not True:
            return "sealed backend provider call values were invalid"
        if "call_count" in details and details["call_count"] != 1:
            return "sealed backend provider call values were invalid"
        if (
            "readiness" in details
            and details["readiness"] != "ready_at_call_boundary"
        ):
            return "sealed backend provider call values were invalid"
        if (
            "cache_decision" in details
            and details["cache_decision"] != "bypassed_fresh_direct_call"
        ):
            return "sealed backend provider call values were invalid"
        if (
            "effective_seed" in details
            and details["effective_seed"] is not None
            and (
                isinstance(details["effective_seed"], bool)
                or not isinstance(details["effective_seed"], int)
            )
        ):
            return "sealed backend provider call values were invalid"
        if (
            "seed_control" in details
            and not _safe_public_string(details["seed_control"])
        ):
            return "sealed backend provider call values were invalid"
        identity = details.get("provider_identity")
        if (
            identity is not None
            and not _provider_identity_values_are_valid(identity)
        ):
            return "sealed backend provider identity schema was not closed"
        result = details.get("result")
        if result is not None:
            if (
                not isinstance(result, dict)
                or set(result) != {"status", "summary"}
                or result.get("status") != "succeeded"
                or not isinstance(result.get("summary"), dict)
                or not result["summary"]
            ):
                return "sealed backend provider result schema was not closed"
            summary = result.get("summary")
            operation = call.get("operation")
            if (
                summary is not None
                and (
                    not isinstance(operation, str)
                    or not _provider_summary_values_are_valid(
                        operation,
                        summary,
                    )
                )
            ):
                return "sealed backend provider summary schema was not closed"
        tiebreak = details.get("correspondence_tiebreak")
        if tiebreak is not None and (
            not isinstance(tiebreak, dict)
            or set(tiebreak) != {"model", "provider", "tmtools_version"}
            or tiebreak.get("provider") != "tmtools"
            or tiebreak.get("model") != "tm_align-sequence-tiebreak"
            or not _safe_public_string(tiebreak.get("tmtools_version"))
        ):
            return "sealed backend tiebreak schema was not closed"
        operation = call.get("operation")
        production_manifest = "created_at" in backend
        if (
            production_manifest
            and operation in _CALL_DETAIL_KEYS
            and "input_identity" not in details
        ):
            return "sealed backend scientific input schema was not closed"
        if (
            isinstance(operation, str)
            and operation in _CALL_DETAIL_KEYS
            and "input_identity" in details
        ):
            try:
                validate_provider_call_details(
                    str(operation),
                    {
                        key: value
                        for key, value in details.items()
                        if key in _CALL_DETAIL_KEYS[str(operation)]
                    },
                )
            except ValueError:
                return "sealed backend scientific input schema was not closed"

    reduced_event_schemas = {
        "run_started": {"node_order", "project_id", "run_id", "sequence", "type"},
        "node_state": {
            "node_id",
            "project_id",
            "run_id",
            "sequence",
            "state",
            "type",
        },
        "node_completed": {
            "node_id",
            "project_id",
            "run_id",
            "sequence",
            "type",
        },
        "run_completed": {"project_id", "run_id", "sequence", "type"},
    }
    production_event_schemas = {
        "run_started": reduced_event_schemas["run_started"]
        | {"status", "timestamp"},
        "node_state": reduced_event_schemas["node_state"]
        | {"old_state", "timestamp"},
        "node_completed": reduced_event_schemas["node_completed"]
        | {"old_state", "output_summary", "state", "timestamp"},
        "run_completed": reduced_event_schemas["run_completed"]
        | {"duration_ms", "status", "timestamp"},
    }
    events = sealed.get("websocket_events")
    if (
        not isinstance(events, list)
        or any(
            not isinstance(event, dict)
            or not isinstance(event.get("type"), str)
            or event["type"] not in reduced_event_schemas
            or set(event)
            not in (
                reduced_event_schemas[event["type"]],
                production_event_schemas[event["type"]],
            )
            for event in events
        )
    ):
        return "sealed WebSocket event schema was not closed"
    for event in events:
        if (
            not _safe_identifier(event.get("project_id"))
            or not _safe_identifier(event.get("run_id"))
            or isinstance(event.get("sequence"), bool)
            or not isinstance(event.get("sequence"), int)
            or event["sequence"] < 1
            or (
                "node_id" in event
                and not _safe_identifier(event["node_id"])
            )
            or (
                "node_order" in event
                and not _safe_identifier_list(event["node_order"])
            )
        ):
            return "sealed WebSocket event values were invalid"
        if "timestamp" in event and not _timezone_aware_iso_timestamp(
            event["timestamp"]
        ):
            return "sealed WebSocket timestamp was invalid"
        if event["type"] == "run_started" and "status" in event:
            if event["status"] != "running":
                return "sealed run-start status was invalid"
        if event["type"] == "run_completed" and "status" in event:
            if (
                event["status"] != "completed"
                or isinstance(event["duration_ms"], bool)
                or not isinstance(event["duration_ms"], int)
                or event["duration_ms"] < 0
            ):
                return "sealed run-completion details were invalid"
        if event["type"] in {"node_state", "node_completed"}:
            if (
                "old_state" in event
                and not _safe_public_string(event["old_state"])
            ) or (
                "state" in event
                and not _safe_public_string(event["state"])
            ):
                return "sealed Node state details were invalid"
        output_summary = event.get("output_summary")
        if output_summary is not None and (
            not isinstance(output_summary, dict)
            or set(output_summary) != {"cache", "output_ports"}
            or not isinstance(output_summary.get("cache"), dict)
            or set(output_summary["cache"]) != {"outcome"}
            or output_summary["cache"]["outcome"]
            not in {"bypass", "hit", "miss"}
            or not isinstance(output_summary.get("output_ports"), list)
            or len(output_summary["output_ports"]) > 128
            or any(
                not _safe_public_string(port)
                for port in output_summary["output_ports"]
            )
        ):
            return "sealed Node output summary was invalid"
    retained_artifacts = sealed.get("artifacts")
    if (
        not isinstance(retained_artifacts, list)
        or any(
            not isinstance(artifact, dict)
            or set(artifact)
            != {
                "candidate_id",
                "reference",
                "retained_path",
                "sha256",
                "size",
            }
            for artifact in retained_artifacts
        )
    ):
        return "sealed retained artifact schema was not closed"
    if any(
        not _safe_identifier(artifact["candidate_id"])
        or not _safe_public_string(artifact["reference"])
        or not _safe_public_string(artifact["retained_path"])
        or isinstance(artifact["size"], bool)
        or not isinstance(artifact["size"], int)
        or artifact["size"] <= 0
        or not isinstance(artifact["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
        for artifact in retained_artifacts
    ):
        return "sealed retained artifact values were invalid"
    return None


def validate_fresh_bundle(
    result_dir: Path,
    *,
    expected_revision: str,
    provider_events: list[dict[str, object]],
) -> tuple[str | None, str | None]:
    """Fail closed unless the fresh-run test sealed all public evidence."""
    manifest_path = result_dir / "sealed-manifest.json"
    try:
        sealed = json.loads(
            _read_stable_private_file(
                manifest_path,
                maximum_bytes=16 * 1024 * 1024,
            )
        )
    except (OSError, ValueError, json.JSONDecodeError):
        if not manifest_path.exists():
            return None, "sealed manifest was not a bounded regular file"
        return None, "sealed manifest was not readable JSON"
    schema_error = _fresh_manifest_schema_error(sealed)
    if schema_error is not None:
        return None, schema_error
    if (
        not isinstance(sealed, dict)
        or sealed.get("schema_version") != 1
        or sealed.get("fresh_run") is not True
        or sealed.get("historical_cache_allowed") is not False
        or sealed.get("secrets_retained") is not False
        or sealed.get("project_id") != "canonical-3gb1"
        or sealed.get("source") != {
            "revision": expected_revision,
            "dirty": False,
        }
        or sealed.get("providers", {}).get("validated_real_events")
        != provider_events
    ):
        return None, "sealed manifest did not match the fresh gate"
    run_id = sealed.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return None, "sealed manifest run identity was missing"
    backend_manifest = sealed.get("backend_manifest")
    if not isinstance(backend_manifest, dict):
        return None, "sealed backend manifest was missing"
    backend_manifest_sha256 = hashlib.sha256(
        json.dumps(
            backend_manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    if (
        backend_manifest_sha256 != sealed.get("backend_manifest_sha256")
        or backend_manifest.get("run_id") != run_id
        or backend_manifest.get("source") != sealed.get("source")
    ):
        return None, "sealed backend manifest digest did not match"
    backend_readiness = backend_manifest.get("providers", {}).get(
        "readiness"
    )
    wrapper_readiness = [
        event
        for event in provider_events
        if event.get("event_type") == "provider_readiness"
    ]
    if not isinstance(backend_readiness, list):
        return None, "sealed backend readiness was missing"
    backend_readiness_by_provider = {
        str(fact.get("provider")): (
            fact.get("ready"),
            fact.get("provider_identity"),
        )
        for fact in backend_readiness
        if isinstance(fact, dict)
    }
    wrapper_readiness_by_provider = {
        str(fact.get("provider")): (
            fact.get("ready"),
            fact.get("provider_identity"),
        )
        for fact in wrapper_readiness
        if isinstance(fact, dict)
    }
    if (
        len(backend_readiness_by_provider) != len(backend_readiness)
        or len(wrapper_readiness_by_provider) != len(wrapper_readiness)
        or backend_readiness_by_provider != wrapper_readiness_by_provider
    ):
        return None, "backend and wrapper readiness identities differ"
    artifacts = sealed.get("artifacts")
    artifact_root = result_dir / "artifacts"
    checksum_path = result_dir / "artifact-checksums.sha256"
    try:
        if (
            artifact_root.is_symlink()
            or not artifact_root.is_dir()
            or not isinstance(artifacts, list)
            or len(artifacts) != 15
        ):
            return None, "sealed artifact inventory was incomplete"
        retained_files = sorted(
            path
            for path in artifact_root.iterdir()
            if path.is_file() and not path.is_symlink()
        )
    except OSError:
        return None, "sealed artifact inventory was not readable"
    if len(retained_files) != 15 or len(list(artifact_root.iterdir())) != 15:
        return None, "sealed artifact inventory did not contain exactly 15 files"

    checksum_lines: list[str] = []
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            return None, "sealed artifact record was invalid"
        relative = artifact.get("retained_path")
        expected_size = artifact.get("size")
        expected_sha256 = artifact.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative.startswith("artifacts/")
            or Path(relative).parts != ("artifacts", Path(relative).name)
            or relative in seen_paths
            or not isinstance(expected_size, int)
            or expected_size <= 0
            or not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        ):
            return None, "sealed artifact record was invalid"
        seen_paths.add(relative)
        path = result_dir / relative
        try:
            payload = _read_stable_private_file(
                path,
                maximum_bytes=16 * 1024 * 1024,
            )
            if len(payload) != expected_size:
                return None, "sealed artifact did not match its record"
        except (OSError, ValueError):
            return None, "sealed artifact was not readable"
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            return None, "sealed artifact SHA-256 did not match its record"
        checksum_lines.append(f"{expected_sha256}  {relative}\n")
    try:
        checksum_payload = _read_stable_private_file(
            checksum_path,
            maximum_bytes=64 * 1024,
        )
        if checksum_payload.decode() != "".join(checksum_lines):
            return None, "artifact checksum seal did not match retained PDBs"
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "artifact checksum seal was not readable"

    required_root_files = {
        "artifact-checksums.sha256",
        "command-transcript.txt",
        "environment-summary.json",
        "provider-calls.jsonl",
        "provider-summary.json",
        "pytest.xml",
        "sealed-manifest.json",
    }
    bundle_checksum_path = result_dir / "bundle-checksums.sha256"
    try:
        root_entries = {path.name for path in result_dir.iterdir()}
        if root_entries not in {
            frozenset({*required_root_files, "artifacts"}),
            frozenset({
                *required_root_files,
                "artifacts",
                bundle_checksum_path.name,
            }),
        }:
            return None, "fresh evidence bundle contained an unexpected path"
        artifact_root_stat = artifact_root.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(artifact_root_stat.st_mode)
            or artifact_root_stat.st_uid != os.getuid()
            or stat.S_IMODE(artifact_root_stat.st_mode) & 0o077
        ):
            return None, "fresh evidence artifact directory was unsafe"
        for file_name in required_root_files:
            _read_stable_private_file(
                result_dir / file_name,
                maximum_bytes=16 * 1024 * 1024,
            )
    except OSError:
        return None, "fresh evidence bundle inventory was not readable"
    except ValueError:
        return None, "fresh evidence bundle file metadata was unsafe"

    expected_descendants = {
        *required_root_files,
        "artifacts",
        *seen_paths,
    }
    if bundle_checksum_path.name in root_entries:
        expected_descendants.add(bundle_checksum_path.name)
    try:
        observed_descendants = {
            path.relative_to(result_dir).as_posix()
            for path in result_dir.rglob("*")
        }
    except OSError:
        return None, "fresh evidence bundle inventory was not readable"
    if observed_descendants != expected_descendants:
        return None, "fresh evidence bundle contained an unexpected path"

    call_events = [
        event
        for event in provider_events
        if event.get("event_type") == "provider_call"
    ]
    fresh_node_ids = {
        item.get("node_id")
        for item in backend_manifest.get("modules", [])
        if isinstance(item, dict)
    }
    observed_call_nodes = Counter(
        (
            str(event.get("provider")),
            str(event.get("operation")),
            str(event.get("node_id")),
        )
        for event in call_events
    )
    if (
        observed_call_nodes != FRESH_CALL_NODE_COUNT_MAP
        or any(
        event.get("run_id") != run_id
        or event.get("node_id") not in fresh_node_ids
        for event in call_events
        )
    ):
        return None, "provider evidence was not bound to the fresh run"
    manifest_operation_to_evidence = {
        ("local_open", "generate(track=sequence)"): "esm3.generate_sequence",
        ("local_open", "generate(track=structure)"): "esm3.generate_structure",
        ("biohub", "fold"): "esmfold2.fold",
    }
    backend_call_nodes = Counter(
        (
            str(call.get("provider")),
            manifest_operation_to_evidence.get(
                (
                    str(call.get("provider")),
                    str(call.get("operation")),
                ),
                str(call.get("operation")),
            ),
            str(call.get("details", {}).get("node_id")),
        )
        for call in backend_manifest.get("providers", {}).get("calls", [])
        if isinstance(call, dict)
    )
    if backend_call_nodes != observed_call_nodes:
        return None, "backend and wrapper scientific calls differ"

    lineage = backend_manifest.get("candidate_lineage")
    scores = backend_manifest.get("scores")
    if not isinstance(lineage, list) or not isinstance(scores, list):
        return None, "sealed backend result facts were incomplete"

    def lineage_entries(
        node_id: str,
        output_port: str,
    ) -> list[dict[str, object]]:
        return [
            entry
            for entry in lineage
            if (
                isinstance(entry, dict)
                and entry.get("node_id") == node_id
                and entry.get("output_port") == output_port
            )
        ]

    sequence_entries = lineage_entries(
        "esm3_gen",
        "sequence_candidates",
    )
    structure_entries = lineage_entries(
        "esm3_gen",
        "structure_candidates",
    )
    initial_entries = lineage_entries("fold_seq", "candidates")
    selected_entries = lineage_entries("top3", "candidates")
    mpnn_entries = lineage_entries("mpnn_0", "candidates")
    final_entries = lineage_entries("final_fold", "candidates")

    def call_subset(
        provider: str,
        operation: str,
        node_id: str,
    ) -> list[dict[str, object]]:
        return [
            event
            for event in call_events
            if (
                event.get("provider") == provider
                and event.get("operation") == operation
                and event.get("node_id") == node_id
            )
        ]

    sequence_calls = call_subset(
        "local_open",
        "esm3.generate_sequence",
        "esm3_gen",
    )
    structure_calls = call_subset(
        "local_open",
        "esm3.generate_structure",
        "esm3_gen",
    )
    initial_calls = call_subset(
        "biohub",
        "esmfold2.fold",
        "fold_seq",
    )
    mpnn_calls = call_subset(
        "local-proteinmpnn",
        "design_sequences",
        "mpnn_0",
    )

    def candidate_parent_map(
        entries: list[dict[str, object]],
    ) -> dict[object, object]:
        return {
            entry.get("candidate_id"): (
                entry.get("parent_ids", [None])[0]
                if isinstance(entry.get("parent_ids"), list)
                and len(entry["parent_ids"]) == 1
                else None
            )
            for entry in entries
        }

    if (
        {event.get("candidate_id") for event in sequence_calls}
        != {entry.get("candidate_id") for entry in sequence_entries}
        or {
            event.get("candidate_id"): event.get("parent_candidate_id")
            for event in structure_calls
        }
        != candidate_parent_map(structure_entries)
        or {
            event.get("candidate_id"): event.get("parent_candidate_id")
            for event in initial_calls
        }
        != candidate_parent_map(initial_entries)
    ):
        return None, "provider Candidate lineage did not match the fresh run"

    mpnn_event_parent_by_candidate: dict[object, object] = {}
    for event in mpnn_calls:
        candidate_ids = event.get("candidate_ids")
        if not isinstance(candidate_ids, list) or len(candidate_ids) != 5:
            return None, "ProteinMPNN provider lineage was incomplete"
        for candidate_id in candidate_ids:
            if candidate_id in mpnn_event_parent_by_candidate:
                return None, "ProteinMPNN provider lineage was incomplete"
            mpnn_event_parent_by_candidate[candidate_id] = event.get(
                "parent_candidate_id"
            )
    if (
        mpnn_event_parent_by_candidate != candidate_parent_map(mpnn_entries)
        or Counter(mpnn_event_parent_by_candidate.values())
        != Counter({
            entry.get("candidate_id"): 5
            for entry in selected_entries
        })
    ):
        return None, "ProteinMPNN provider lineage was incomplete"

    final_folds = [
        event
        for event in call_events
        if (
            event.get("provider") == "biohub"
            and event.get("operation") == "esmfold2.fold"
            and event.get("node_id") == "final_fold"
        )
    ]
    artifact_by_candidate = {
        artifact["candidate_id"]: artifact for artifact in artifacts
    }
    final_parent_by_candidate = candidate_parent_map(final_entries)
    if (
        len(final_folds) != 15
        or {event.get("candidate_id") for event in final_folds}
        != set(artifact_by_candidate)
        or {
            event.get("candidate_id"): event.get("parent_candidate_id")
            for event in final_folds
        }
        != final_parent_by_candidate
        or any(
            event.get("result", {}).get("summary", {}).get("pdb_sha256")
            != artifact_by_candidate[event["candidate_id"]]["sha256"]
            for event in final_folds
        )
    ):
        return None, "final provider calls did not match retained PDB lineage"

    for node_id, score_id in (
        ("tm_3gb1", "tm_vs_3gb1"),
        ("tm_esm3", "tm_vs_esm3"),
    ):
        tm_events = call_subset("tmtools", "tm_score", node_id)
        tm_scores = [
            score
            for score in scores
            if (
                isinstance(score, dict)
                and score.get("node_id") == node_id
                and score.get("score_id") == score_id
            )
        ]
        if len(tm_events) != len(tm_scores):
            return None, "TM provider results did not match manifest scores"
        try:
            tm_values_match = all(
                round(
                    float(
                        event.get("result", {})
                        .get("summary", {})
                        .get("value")
                    ),
                    4,
                )
                == float(score.get("value"))
                for event, score in zip(tm_events, tm_scores, strict=True)
            )
        except (AttributeError, TypeError, ValueError):
            tm_values_match = False
        if not tm_values_match:
            return None, "TM provider results did not match manifest scores"

    if bundle_checksum_path.name in root_entries:
        expected_bundle_lines: list[str] = []
        try:
            for path in sorted(
                candidate
                for candidate in result_dir.rglob("*")
                if candidate.is_file()
                and candidate != bundle_checksum_path
            ):
                payload = _read_stable_private_file(
                    path,
                    maximum_bytes=16 * 1024 * 1024,
                )
                relative = path.relative_to(result_dir).as_posix()
                expected_bundle_lines.append(
                    f"{hashlib.sha256(payload).hexdigest()}  {relative}\n"
                )
            observed_bundle = _read_stable_private_file(
                bundle_checksum_path,
                maximum_bytes=64 * 1024,
            ).decode()
        except (OSError, UnicodeDecodeError, ValueError):
            return None, "bundle checksum seal was not readable"
        if observed_bundle != "".join(expected_bundle_lines):
            return None, "bundle checksum seal did not match retained evidence"
    return run_id, None


def _freeze_bundle_permissions(result_dir: Path) -> None:
    files = sorted(path for path in result_dir.rglob("*") if path.is_file())
    for path in files:
        path.chmod(0o400)
    for path in sorted(
        (candidate for candidate in result_dir.rglob("*") if candidate.is_dir()),
        reverse=True,
    ):
        path.chmod(0o500)
    result_dir.chmod(0o500)


def seal_bundle_checksums(result_dir: Path) -> Path:
    """Hash every retained evidence file after all writers are finished."""
    checksum_path = result_dir / "bundle-checksums.sha256"
    lines: list[str] = []
    files = sorted(
        path for path in result_dir.rglob("*") if path.is_file()
    )
    for path in files:
        if path == checksum_path or not path.is_file():
            continue
        payload = _read_stable_private_file(
            path,
            maximum_bytes=16 * 1024 * 1024,
        )
        relative = path.relative_to(result_dir).as_posix()
        lines.append(f"{hashlib.sha256(payload).hexdigest()}  {relative}\n")
    temporary_path = result_dir / ".bundle-checksums.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary_path, flags, 0o600)
    try:
        payload = "".join(lines).encode()
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("bundle checksum write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.rename(temporary_path, checksum_path)
    directory_descriptor = os.open(result_dir, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    if _read_stable_private_file(
        checksum_path,
        maximum_bytes=64 * 1024,
    ) != payload:
        raise ValueError("bundle checksum seal failed verification")
    _freeze_bundle_permissions(result_dir)
    return checksum_path


def main() -> int:
    args = _parse_args()
    tier = TIERS[args.tier]
    provider_evidence_gate = tier.provider_evidence_gate or args.tier
    process_timeout_seconds = tier.timeout_seconds
    termination_grace_seconds = tier.termination_grace_seconds
    timeout_probe = (
        args.tier == "routine"
        and args.pytest_targets
        == ["tests/tier_probes/process_timeout_probe.py"]
        and os.environ.get("PROTEIN_WORKBENCH_PROCESS_TIMEOUT_PROBE") == "1"
    )
    if timeout_probe:
        process_timeout_seconds = 1
        termination_grace_seconds = 7
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
    result_dir = (
        results_root
        / args.tier
        / f"{run_id}-{os.getpid()}-{secrets.token_hex(8)}"
    )
    environment_summary = _environment_summary(args.tier)
    gate_started_at = datetime.now(timezone.utc)
    gate_nonce = secrets.token_urlsafe(32)

    with tempfile.TemporaryDirectory(
        prefix=f"protein-workbench-{args.tier}-"
    ) as temporary_root:
        base = Path(temporary_root)
        env = _child_environment(args.tier, tier, base)
        for variable in ROOT_VARIABLES:
            name = variable.removeprefix("PROTEIN_WORKBENCH_").removesuffix("_ROOT")
            root = base / name.lower()
            root.mkdir()
            env[variable] = str(root)
        env["PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED"] = "1"
        env["PROTEIN_WORKBENCH_VERIFICATION_TIER"] = (
            provider_evidence_gate
        )
        if tier.provider_identity_profile is not None:
            env["PROTEIN_WORKBENCH_PROVIDER_IDENTITY_PROFILE"] = (
                tier.provider_identity_profile
            )
        if tier.requires_provider_evidence:
            env["PROTEIN_WORKBENCH_PROVIDER_EVIDENCE_SCOPE"] = ",".join(
                sorted({
                    provider
                    for provider, _operation
                    in tier.expected_call_counts
                })
            )
        env["PROTEIN_WORKBENCH_REAL_GATE_NONCE"] = gate_nonce
        env["PROTEIN_WORKBENCH_REAL_GATE_FRESH"] = "1"
        if timeout_probe:
            env["PROTEIN_WORKBENCH_PROCESS_TIMEOUT_PROBE"] = "1"
        if tier.requires_fresh_bundle:
            env["PROTEIN_WORKBENCH_PROCESS_CONTAINMENT"] = (
                "shared_process_group"
            )
        if initial_source_attestation is not None:
            env["PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION"] = (
                initial_source_attestation[0]
            )
        if args.tier == "deterministic-acceptance":
            for variable in (
                "PROTEIN_WORKBENCH_CANONICAL_WORKFLOW",
                "PROTEIN_WORKBENCH_CANONICAL_UI",
                "PROTEIN_WORKBENCH_CANONICAL_VERSION",
                "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
                "PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL",
            ):
                env.pop(variable, None)

        evidence_staging_root = base / "evidence-staging"
        evidence_staging_root.mkdir(mode=0o700)
        call_evidence = evidence_staging_root / "provider-calls.jsonl"
        env["PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE"] = str(call_evidence)
        fresh_evidence_staging = evidence_staging_root / "fresh-bundle"
        if tier.requires_fresh_bundle:
            env["PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_ROOT"] = str(
                fresh_evidence_staging
            )
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

        junit_path = base / "pytest.xml"
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
        control_read, control_write = os.pipe()
        status_read, status_write = os.pipe()
        supervised_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            PROCESS_SUPERVISOR_FLAG,
            str(control_read),
            str(status_write),
            *command,
        ]
        resource_cleanup_warning = False
        process = subprocess.Popen(
            supervised_command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=(control_read, status_write),
        )
        os.close(control_read)
        os.close(status_write)
        timed_out = threading.Event()
        released = threading.Event()
        timeout_handler_done = threading.Event()
        decision_lock = threading.Lock()
        escalation_timer: threading.Timer | None = None

        def terminate_timed_out_process() -> None:
            nonlocal escalation_timer
            try:
                with decision_lock:
                    if released.is_set():
                        return
                    timed_out.set()
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass

                    def kill_process_group() -> None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

                    escalation_timer = threading.Timer(
                        termination_grace_seconds,
                        kill_process_group,
                    )
                    escalation_timer.daemon = True
                    escalation_timer.start()
            finally:
                timeout_handler_done.set()

        timer = threading.Timer(
            process_timeout_seconds,
            terminate_timed_out_process,
        )
        status_file = os.fdopen(status_read, "rb")
        normal_child_done = False
        return_code = 1
        try:
            readable, _, _ = select.select(
                [status_file],
                [],
                [],
                10,
            )
            if not readable or status_file.readline() != b"READY\n":
                raise RuntimeError(
                    "verification process supervisor did not become ready"
                )
            timer.start()
            resource_cleanup_warning = _stream_process_output(process)
            done_line = status_file.readline()
            if (
                not done_line.startswith(b"DONE:")
                or not done_line.endswith(b"\n")
            ):
                if timed_out.is_set():
                    return_code = process.poll() or 1
                else:
                    raise RuntimeError(
                        "verification process supervisor lost child status"
                    )
            else:
                return_code = int(done_line[5:-1])
                normal_child_done = True
                if timeout_probe:
                    if (
                        not timed_out.wait(
                            timeout=process_timeout_seconds + 2
                        )
                        or not timeout_handler_done.wait(timeout=2)
                    ):
                        raise RuntimeError(
                            "controlled timeout probe did not acquire timeout"
                        )
                    print(
                        "PROCESS TIMEOUT PROBE: timeout acquired",
                        flush=True,
                    )
        finally:
            timer.cancel()
            control_is_open = True
            try:
                with decision_lock:
                    if normal_child_done and not timed_out.is_set():
                        released.set()
                    control_is_open = _finish_supervisor_control(
                        control_write,
                        normal_child_done=normal_child_done,
                        timed_out=timed_out.is_set(),
                    )
                status_file.close()
                if timed_out.is_set():
                    timeout_handler_done.wait(timeout=15)
                if escalation_timer is not None:
                    if timed_out.is_set():
                        escalation_timer.join(
                            timeout=termination_grace_seconds + 1
                        )
                    else:
                        escalation_timer.cancel()
                        escalation_timer.join(timeout=1)
                try:
                    process.wait(
                        timeout=max(
                            6,
                            termination_grace_seconds + 1,
                        )
                    )
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            finally:
                if control_is_open:
                    os.close(control_write)
        completed = subprocess.CompletedProcess(
            command,
            return_code,
        )
        result_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        result_dir.parent.chmod(0o700)
        result_dir.mkdir(mode=0o700)
        result_dir.chmod(0o700)
        print(f"RETAINED VERIFICATION RESULT: {result_dir}", flush=True)
        _write_json_once(
            result_dir / "environment-summary.json",
            environment_summary,
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
        transcript_header = (
            "cwd=$PROJECT_ROOT\n"
            f"$ {shlex.join(display_command)}\n"
            f"return_code={completed.returncode}\n"
        )

        if timed_out.is_set():
            _write_private_file_once(
                transcript_path,
                transcript_header.encode(),
            )
            print(
                "BACKEND VERIFICATION RESULT: failed (tier timeout)",
                flush=True,
            )
            return 1
        if not junit_path.exists():
            _write_private_file_once(
                transcript_path,
                transcript_header.encode(),
            )
            print("BACKEND VERIFICATION RESULT: failed (no JUnit result)", flush=True)
            return completed.returncode or 1

        try:
            _sanitize_junit(junit_path)
        except (OSError, ValueError, ET.ParseError):
            _write_private_file_once(
                transcript_path,
                transcript_header.encode(),
            )
            print(
                "BACKEND VERIFICATION RESULT: failed (invalid JUnit result)",
                flush=True,
            )
            return 1
        tests, failures, skipped = _junit_counts(junit_path)
        _write_private_file_once(
            transcript_path,
            (
                transcript_header
                + f"tests={tests} failures={failures} skipped={skipped}\n"
                + "resource_cleanup_warning="
                + f"{str(resource_cleanup_warning).lower()}\n"
            ).encode(),
        )
        try:
            _publish_private_file(
                junit_path,
                result_dir / "pytest.xml",
                maximum_bytes=MAX_JUNIT_BYTES,
            )
        except (OSError, ValueError):
            print(
                "BACKEND VERIFICATION RESULT: failed "
                "(sanitized JUnit publication failed)",
                flush=True,
            )
            return 1
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
        evidence: list[dict[str, object]] = []
        if tier.requires_provider_evidence and not call_evidence.exists():
            evidence_error = "no provider-call evidence was recorded"
        elif tier.requires_provider_evidence:
            evidence, evidence_error = validate_provider_evidence(
                call_evidence,
                tier_name=provider_evidence_gate,
                tier=tier,
                nonce=gate_nonce,
                started_at=gate_started_at,
                focused=bool(args.pytest_targets),
            )
            if evidence:
                try:
                    _publish_provider_events(
                        result_dir / "provider-calls.jsonl",
                        evidence,
                    )
                except (OSError, ValueError):
                    evidence_error = (
                        "validated provider evidence publication failed"
                    )
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
                _write_json_once(
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
        if tier.requires_fresh_bundle:
            try:
                fresh_quarantine = Path(tempfile.mkdtemp(
                    prefix="parent-fresh-quarantine-",
                    dir=base,
                ))
                fresh_quarantine.chmod(0o700)
                for name, maximum_bytes in (
                    ("command-transcript.txt", 64 * 1024),
                    ("environment-summary.json", 64 * 1024),
                    ("provider-calls.jsonl", 2 * 1024 * 1024),
                    ("provider-summary.json", 2 * 1024 * 1024),
                    ("pytest.xml", MAX_JUNIT_BYTES),
                ):
                    _publish_private_file(
                        result_dir / name,
                        fresh_quarantine / name,
                        maximum_bytes=maximum_bytes,
                    )
                _publish_fresh_evidence(
                    fresh_evidence_staging,
                    fresh_quarantine,
                )
            except (OSError, ValueError):
                print(
                    "BACKEND VERIFICATION RESULT: failed "
                    "(fresh evidence publication failed)",
                    flush=True,
                )
                return 1
            run_id, bundle_error = validate_fresh_bundle(
                fresh_quarantine,
                expected_revision=initial_source_attestation[0],
                provider_events=evidence,
            )
            if bundle_error is not None:
                print(
                    "BACKEND VERIFICATION RESULT: failed "
                    f"(invalid fresh-run bundle: {bundle_error})",
                    flush=True,
                )
                return 1
            seal_bundle_checksums(fresh_quarantine)
            sealed_run_id, sealed_bundle_error = validate_fresh_bundle(
                fresh_quarantine,
                expected_revision=initial_source_attestation[0],
                provider_events=evidence,
            )
            if sealed_bundle_error is not None or sealed_run_id != run_id:
                print(
                    "BACKEND VERIFICATION RESULT: failed "
                    "(final bundle checksum verification failed)",
                    flush=True,
                )
                return 1
            try:
                _publish_validated_fresh_bundle(
                    fresh_quarantine,
                    result_dir,
                )
            except (OSError, ValueError):
                print(
                    "BACKEND VERIFICATION RESULT: failed "
                    "(validated fresh evidence publication failed)",
                    flush=True,
                )
                return 1
            retained_run_id, retained_bundle_error = validate_fresh_bundle(
                result_dir,
                expected_revision=initial_source_attestation[0],
                provider_events=evidence,
            )
            if (
                retained_bundle_error is not None
                or retained_run_id != run_id
            ):
                print(
                    "BACKEND VERIFICATION RESULT: failed "
                    "(retained bundle verification failed)",
                    flush=True,
                )
                return 1
            _freeze_bundle_permissions(result_dir)
            print(f"FRESH REMOTE RUN ID: {run_id}", flush=True)
            print(f"SEALED EVIDENCE BUNDLE: {result_dir}", flush=True)

        print("BACKEND VERIFICATION RESULT: passed", flush=True)
        return 0


if __name__ == "__main__":
    if (
        len(sys.argv) >= 5
        and sys.argv[1] == PROCESS_SUPERVISOR_FLAG
    ):
        raise SystemExit(supervise_verification_process_group(
            sys.argv[4:],
            control_descriptor=int(sys.argv[2]),
            status_descriptor=int(sys.argv[3]),
        ))
    raise SystemExit(main())
