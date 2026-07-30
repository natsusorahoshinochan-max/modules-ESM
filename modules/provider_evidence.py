"""Fresh, redacted acceptance evidence for Module provider boundaries."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.storage import validate_identifier


EVIDENCE_VERSION = 1
_MAX_EVENT_BYTES = 16 * 1024
_OPAQUE_API_TOKEN = re.compile(
    r"\b(?:"
    r"(?:sk|pk)-[A-Za-z0-9_-]{8,}|"
    r"hf_[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}"
    r")\b"
)
_IDENTITY_KEYS = frozenset({
    "algorithm",
    "artifact_sha256",
    "binary",
    "biopython_version",
    "checkpoint_sha256",
    "esm2_artifact_sha256",
    "esm2_source_revision",
    "esm2_source_tree_sha256",
    "numpy_version",
    "required_version",
    "sdk",
    "sdk_source_revision",
    "service",
    "snapshot_revision",
    "source",
    "source_revision",
    "tmtools_version",
    "weight_sha256",
})
_READINESS_DETAIL_KEYS = frozenset({
    "artifact_contract_complete",
    "checkout_and_checkpoint_validated",
    "credential_present",
    "installed",
    "snapshot_validated",
    "version_match",
})
_RESULT_KEYS = {
    "esm3.generate_sequence": frozenset({
        "result_type",
        "has_sequence",
        "has_coordinates",
        "input_sequence_length",
        "input_sequence_sha256",
        "secondary_structure_length",
        "secondary_structure_sha256",
        "output_sequence_length",
        "output_sequence_sha256",
    }),
    "esm3.generate_structure": frozenset({
        "result_type",
        "has_sequence",
        "has_coordinates",
        "input_sequence_length",
        "input_sequence_sha256",
        "secondary_structure_length",
        "secondary_structure_sha256",
        "output_sequence_length",
        "output_sequence_sha256",
    }),
    "esmfold2.fold": frozenset({
        "input_sequence_length",
        "input_sequence_sha256",
        "pdb_bytes",
        "pdb_sha256",
        "score_ids",
    }),
    "design_sequences": frozenset({
        "input_pdb_sha256",
        "sequence_count",
        "sequence_lengths",
        "sequence_sha256",
        "score_count",
        "score_min",
        "score_max",
    }),
    "score_sequence": frozenset({
        "input_pdb_sha256",
        "input_sequence_sha256",
        "score",
        "sequence_length",
    }),
    "structure_align": frozenset({
        "reference_length",
        "mobile_length",
        "aligned_residues",
        "rmsd",
        "coverage",
    }),
    "structure_align_tiebreak": frozenset({
        "reference_length",
        "mobile_length",
        "aligned_residues",
    }),
    "tm_score": frozenset({
        "value",
        "normalization",
        "normalization_length",
        "aligned_residues",
        "reference_coverage",
        "d0",
    }),
    "secondary_structure": frozenset({
        "return_code",
        "output_bytes",
        "output_sha256",
        "residue_count",
    }),
    "fold_sequence": frozenset({
        "input_sequence_length",
        "input_sequence_sha256",
        "structure_count",
        "pdb_bytes",
        "pdb_sha256",
        "score_count",
        "num_steps",
    }),
    "evaluate_structure": frozenset({
        "input_pdb_sha256",
        "score_count",
        "score_ids",
        "score_values",
    }),
}
_CALL_DETAIL_KEYS = {
    "structure_align": frozenset({
        "candidate_id",
        "correspondence_tiebreak",
        "reference_candidate_id",
        "mobile_candidate_id",
        "reference_input",
        "mobile_input",
        "input_identity",
    }),
    "structure_align_tiebreak": frozenset({
        "candidate_id",
        "reference_candidate_id",
        "mobile_candidate_id",
        "reference_input",
        "mobile_input",
        "input_identity",
    }),
    "tm_score": frozenset({
        "candidate_id",
        "score_id",
        "input_identity",
    }),
}
_INPUT_IDENTITY_KEYS = {
    "structure_align": {
        "reference_pdb_bytes": int,
        "reference_pdb_sha256": str,
        "mobile_pdb_bytes": int,
        "mobile_pdb_sha256": str,
    },
    "structure_align_tiebreak": {
        "reference_pdb_bytes": int,
        "reference_pdb_sha256": str,
        "mobile_pdb_bytes": int,
        "mobile_pdb_sha256": str,
    },
    "tm_score": {
        "tm_align_input_sha256": str,
    },
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _bounded(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _OPAQUE_API_TOKEN.sub("[REDACTED]", value[:512])
    if isinstance(value, (list, tuple)):
        return [_bounded(item) for item in value[:128]]
    if isinstance(value, dict):
        return {
            str(key)[:128]: _bounded(item)
            for key, item in list(value.items())[:128]
        }
    return f"<{type(value).__name__}>"


def _validated_call_details(
    operation: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    allowed_keys = _CALL_DETAIL_KEYS.get(operation)
    identity_schema = _INPUT_IDENTITY_KEYS.get(operation)
    if (
        allowed_keys is None
        or identity_schema is None
        or set(details) - allowed_keys
    ):
        raise ValueError(
            "Provider call details contain non-allowlisted fields"
        )

    safe: dict[str, Any] = {}
    for key in (
        "candidate_id",
        "reference_candidate_id",
        "mobile_candidate_id",
        "score_id",
        "reference_input",
        "mobile_input",
    ):
        if key not in allowed_keys:
            continue
        value = details.get(key)
        if value is None and key == "reference_candidate_id":
            safe[key] = None
        elif value is not None:
            safe[key] = validate_identifier(value, key)

    correspondence_tiebreak = details.get("correspondence_tiebreak")
    if correspondence_tiebreak is not None:
        if (
            not isinstance(correspondence_tiebreak, dict)
            or set(correspondence_tiebreak) != {
                "model",
                "provider",
                "tmtools_version",
            }
            or correspondence_tiebreak.get("provider") != "tmtools"
            or correspondence_tiebreak.get("model")
            != "tm_align-sequence-tiebreak"
        ):
            raise ValueError("Structure alignment tiebreak identity is invalid")
        tmtools_version = correspondence_tiebreak.get("tmtools_version")
        if (
            not isinstance(tmtools_version, str)
            or not re.fullmatch(r"[0-9A-Za-z.+_-]{1,64}", tmtools_version)
        ):
            raise ValueError("Structure alignment tiebreak version is invalid")
        safe["correspondence_tiebreak"] = {
            "provider": "tmtools",
            "model": "tm_align-sequence-tiebreak",
            "tmtools_version": tmtools_version,
        }

    input_identity = details.get("input_identity")
    if (
        not isinstance(input_identity, dict)
        or set(input_identity) != set(identity_schema)
    ):
        raise ValueError("Provider call input identity is incomplete")
    safe_identity: dict[str, Any] = {}
    for key, expected_type in identity_schema.items():
        value = input_identity[key]
        if expected_type is int:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Provider call input byte count is invalid")
        elif not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError("Provider call input digest is invalid")
        safe_identity[key] = value
    safe["input_identity"] = safe_identity

    bounded = _bounded(safe)
    assert isinstance(bounded, dict)
    return bounded


def validate_provider_call_details(
    operation: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Validate and bound scientific call details before engine invocation."""
    return _validated_call_details(operation, details)


def safe_error_type(error_type: Any) -> str:
    """Return a bounded non-secret exception type for public evidence."""
    if (
        not isinstance(error_type, str)
        or _OPAQUE_API_TOKEN.search(error_type) is not None
    ):
        return "Exception"
    try:
        return validate_identifier(error_type, "error_type")
    except ValueError:
        return "Exception"


def _test_id() -> str | None:
    current_test = os.environ.get("PYTEST_CURRENT_TEST")
    if not current_test:
        return None
    return current_test.rsplit(" ", 1)[0][:512]


def _append_event(event: dict[str, Any]) -> bool:
    path_value = os.environ.get("PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE")
    nonce = os.environ.get("PROTEIN_WORKBENCH_REAL_GATE_NONCE")
    gate = os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER")
    if not path_value or not nonce or gate not in {
        "fresh-remote-3gb1",
        "local-provider",
        "heavy-model",
        "live-provider",
    }:
        return False

    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "evidence_version": EVIDENCE_VERSION,
        "run_nonce": nonce,
        "gate": gate,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "event_id": str(uuid4()),
        "test_id": _test_id(),
        **_bounded(event),
    }
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode()
    if len(encoded) > _MAX_EVENT_BYTES:
        raise ValueError("Provider evidence event exceeds the retained size bound")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise OSError("Provider evidence write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o600)
    return True


def record_provider_readiness(
    *,
    provider: str,
    ready: bool,
    identity: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> bool:
    """Record a readiness observation, never an actual provider call."""
    unknown_identity = set(identity) - _IDENTITY_KEYS
    unknown_details = set(details or {}) - _READINESS_DETAIL_KEYS
    if unknown_identity or unknown_details:
        raise ValueError("Provider readiness evidence contains non-allowlisted fields")
    return _append_event({
        "event_type": "provider_readiness",
        "provider": provider,
        "ready": bool(ready),
        "provider_identity": identity,
        "details": details or {},
    })


def _record_provider_call_terminal(
    *,
    provider: str,
    operation: str,
    model: str | None,
    provider_identity: dict[str, Any],
    effective_seed: int | None,
    seed_control: str,
    result: dict[str, Any],
    call_details: dict[str, Any] | None = None,
) -> bool:
    """Record one validated terminal at an actual provider-call boundary."""
    if (
        operation not in _RESULT_KEYS
        or set(provider_identity) - _IDENTITY_KEYS
    ):
        raise ValueError("Provider call evidence contains non-allowlisted fields")
    event = {
        "event_type": "provider_call",
        "provider": provider,
        "operation": operation,
        "model": model,
        "provider_identity": provider_identity,
        "readiness": "ready_at_call_boundary",
        "actual_call": True,
        "call_count": 1,
        "effective_seed": effective_seed,
        "seed_control": seed_control,
        "cache_decision": "bypassed_fresh_direct_call",
        "result": result,
    }
    if call_details is not None:
        validate_provider_call_details(
            operation,
            call_details,
        )
    return _append_event(event)


def record_provider_call_result(
    *,
    provider: str,
    operation: str,
    model: str | None,
    provider_identity: dict[str, Any],
    effective_seed: int | None,
    seed_control: str,
    result_summary: dict[str, Any],
    call_details: dict[str, Any] | None = None,
) -> bool:
    """Record one successfully completed real call at its adapter boundary."""
    allowed_result_keys = _RESULT_KEYS.get(operation)
    if (
        allowed_result_keys is None
        or set(result_summary) - allowed_result_keys
    ):
        raise ValueError("Provider call evidence contains non-allowlisted fields")
    return _record_provider_call_terminal(
        provider=provider,
        operation=operation,
        model=model,
        provider_identity=provider_identity,
        effective_seed=effective_seed,
        seed_control=seed_control,
        result={
            "status": "succeeded",
            "summary": result_summary,
        },
        call_details=call_details,
    )


def record_provider_call_failure(
    *,
    provider: str,
    operation: str,
    model: str | None,
    provider_identity: dict[str, Any],
    effective_seed: int | None,
    seed_control: str,
    error_type: str,
    call_details: dict[str, Any],
) -> bool:
    """Record one failed real call without retaining exception content."""
    return _record_provider_call_terminal(
        provider=provider,
        operation=operation,
        model=model,
        provider_identity=provider_identity,
        effective_seed=effective_seed,
        seed_control=seed_control,
        result={
            "status": "failed",
            "error": {"type": safe_error_type(error_type)},
        },
        call_details=call_details,
    )
