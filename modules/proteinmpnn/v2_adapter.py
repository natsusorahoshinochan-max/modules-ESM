"""Exact local ProteinMPNN v2 Adapter contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import struct
from typing import Any

from core import ReadinessResult
from modules.provider_contract import proteinmpnn_provider_identity
from datatypes import (
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
)

from .provider_runtime import (
    ProteinMPNNDesignRequest,
    ProteinMPNNProvider,
    _LocalProteinMPNNProvider,
    _prepare_design_request,
    check_proteinmpnn_readiness,
)


PROTEINMPNN_MODEL = "v_48_020"
PROTEINMPNN_CHECKPOINT = "vanilla_model_weights/v_48_020.pt"
PROTEINMPNN_DEVICE = "cpu"
PROTEINMPNN_TORCH_VERSION = "2.13.0"
PROTEINMPNN_SCORING_SEED = 42
PROTEINMPNN_NATIVE_SCORE_MAXIMUM = 3.4028234663852886e38
_CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


def proteinmpnn_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    """Validate prerequisites without constructing or loading the model."""
    try:
        if importlib.metadata.version("torch") != PROTEINMPNN_TORCH_VERSION:
            raise RuntimeError("ProteinMPNN Torch identity does not match")
    except (ImportError, importlib.metadata.PackageNotFoundError, RuntimeError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    if environment.get("device") != PROTEINMPNN_DEVICE:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    fingerprint = environment.get("resolved_runtime_fingerprint")
    if fingerprint != configured_runtime_fingerprint():
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    client = environment.get("provider_client")
    if client is not None:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    provider_root = environment.get("provider_root")
    if not isinstance(provider_root, Path):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    readiness = check_proteinmpnn_readiness(
        PROTEINMPNN_MODEL,
        provider_root,
    )
    if (
        not readiness.ready
        or readiness.checkpoint_path is None
        or readiness.checkpoint_path.name != "v_48_020.pt"
    ):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def configured_runtime_fingerprint() -> str:
    """Return the safe exact CPU runtime identity required by this Binding."""
    payload = json.dumps(
        {
            "schema_namespace": "protein-workbench-proteinmpnn-runtime/v2",
            "model": PROTEINMPNN_MODEL,
            "checkpoint": PROTEINMPNN_CHECKPOINT,
            "device": PROTEINMPNN_DEVICE,
            "torch_version": PROTEINMPNN_TORCH_VERSION,
            "provider_identity": proteinmpnn_provider_identity(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def provider_for_environment(
    environment: Mapping[str, Any],
    *,
    staging_directory: Path,
) -> ProteinMPNNProvider:
    """Resolve the declared provider seam without accepting Workflow paths."""
    client = environment.get("provider_client")
    if client is not None:
        raise RuntimeError(
            "ProteinMPNN design does not accept injected provider clients"
        )
    provider_root = environment.get("provider_root")
    if not isinstance(provider_root, Path):
        raise FileNotFoundError(
            "ProteinMPNN provider root is unavailable"
        )
    readiness = check_proteinmpnn_readiness(
        PROTEINMPNN_MODEL,
        provider_root,
    )
    if (
        not readiness.ready
        or readiness.provider_root is None
        or readiness.checkpoint_path is None
        or readiness.checkpoint_path.name != "v_48_020.pt"
    ):
        raise RuntimeError(
            "ProteinMPNN provider root does not match the locked "
            "source and checkpoint identity"
        )
    return _LocalProteinMPNNProvider(
        temp_dir=staging_directory,
        provider_root=readiness.provider_root,
    )


def prepare_design_request(
    *,
    provider: ProteinMPNNProvider,
    structure: ProteinStructure,
    num_sequences: int,
    temperature: float,
    backbone_noise: float,
    seed: int,
    constraints: ProteinMPNNConstraints | None,
    reference_sequence: ProteinSequence | None,
) -> ProteinMPNNDesignRequest:
    """Normalize all public design inputs into one provider request."""
    if type(structure) is not ProteinStructure:
        raise ValueError("structure must be one complete ProteinStructure")
    if constraints is not None and _CANONICAL_AMINO_ACIDS <= set(
        constraints.omit_amino_acids or ()
    ):
        raise ValueError(
            "omit_amino_acids must leave at least one canonical amino acid"
        )
    if (
        reference_sequence is not None
        and not set(reference_sequence.sequence) <= _CANONICAL_AMINO_ACIDS
    ):
        raise ValueError(
            "reference sequence must contain only canonical amino acids"
        )
    parsed = provider.parse_structure(structure.pdb_string)
    request = _prepare_design_request(
        parsed,
        PROTEINMPNN_MODEL,
        num_sequences,
        temperature,
        backbone_noise,
        seed,
        constraints,
        (
            reference_sequence.sequence
            if reference_sequence is not None
            else None
        ),
    )
    if (
        reference_sequence is not None
        and reference_sequence.residue_ids is not None
        and reference_sequence.residue_ids != _target_residue_ids(request)
    ):
        raise ValueError(
            "reference sequence residue layout does not match the "
            "parsed structure layout"
        )
    omitted = list(request.omit_amino_acids)
    if "X" not in omitted:
        omitted.append("X")
    return replace(request, omit_amino_acids=omitted)


def _target_residue_ids(
    request: ProteinMPNNDesignRequest,
) -> list[str]:
    return list(request.target_layout.residue_ids or ())


def _restore_structure_chain_order(
    sequence: str,
    *,
    request: ProteinMPNNDesignRequest,
) -> str:
    entry = request.pdb_dict_list[0]
    chain_lengths = {
        chain: len(str(entry[f"seq_chain_{chain}"]))
        for chain in request.structure_chain_order
    }
    if (
        set(request.provider_chain_order)
        != set(request.structure_chain_order)
        or len(request.provider_chain_order)
        != len(request.structure_chain_order)
    ):
        raise RuntimeError(
            "ProteinMPNN provider chain order is internally inconsistent"
        )
    by_chain: dict[str, str] = {}
    offset = 0
    for chain in request.provider_chain_order:
        chain_end = offset + chain_lengths[chain]
        by_chain[chain] = sequence[offset:chain_end]
        offset = chain_end
    if offset != len(sequence):
        raise RuntimeError(
            "ProteinMPNN provider sequence does not match its chain layout"
        )
    return "".join(by_chain[chain] for chain in request.structure_chain_order)


def validate_design_result(
    raw_result: object,
    *,
    request: ProteinMPNNDesignRequest,
) -> tuple[list[ProteinSequence], list[float] | None]:
    """Fail closed on partial counts, malformed sequences, or bad scores."""
    if (
        not isinstance(raw_result, tuple)
        or len(raw_result) != 2
    ):
        raise RuntimeError(
            "ProteinMPNN provider result must contain sequences and scores"
        )
    raw_sequences, raw_scores = raw_result
    if not isinstance(raw_sequences, list):
        raise RuntimeError("ProteinMPNN provider sequences must be an array")
    if len(raw_sequences) != request.num_sequences:
        raise RuntimeError(
            "ProteinMPNN provider returned "
            f"{len(raw_sequences)} sequences; expected {request.num_sequences}"
        )
    residue_ids = _target_residue_ids(request)
    if len(residue_ids) != request.target_length:
        raise RuntimeError(
            "ProteinMPNN parsed target layout is internally inconsistent"
        )
    sequences: list[ProteinSequence] = []
    for sample_index, sequence in enumerate(raw_sequences):
        if type(sequence) is not ProteinSequence:
            raise RuntimeError(
                f"ProteinMPNN sample {sample_index} is not a ProteinSequence"
            )
        if (
            len(sequence.sequence) != request.target_length
            or not sequence.sequence
            or not set(sequence.sequence) <= _CANONICAL_AMINO_ACIDS
        ):
            raise RuntimeError(
                f"ProteinMPNN sample {sample_index} sequence is malformed"
            )
        if sequence.residue_ids is not None:
            raise RuntimeError(
                f"ProteinMPNN sample {sample_index} provider result must not "
                "pre-label repository residue identities"
            )
        restored_sequence = _restore_structure_chain_order(
            sequence.sequence,
            request=request,
        )
        sequences.append(
            ProteinSequence(restored_sequence, list(residue_ids))
        )
    if raw_scores is None:
        return sequences, None
    if not isinstance(raw_scores, list) or len(raw_scores) != len(sequences):
        raise RuntimeError(
            "ProteinMPNN provider returned incomplete per-sequence scores"
        )
    scores: list[float] = []
    for sample_index, score in enumerate(raw_scores):
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise RuntimeError(
                f"ProteinMPNN sample {sample_index} score is malformed"
            )
        scores.append(float(score))
    return sequences, scores


def prepare_scoring_request(
    *,
    provider: ProteinMPNNProvider,
    structure: ProteinStructure,
    sequence: ProteinSequence,
) -> ProteinMPNNDesignRequest:
    """Normalize one exact Candidate pair into the fixed scoring request."""
    if type(structure) is not ProteinStructure:
        raise ValueError("scoring structure must be one ProteinStructure")
    if (
        type(sequence) is not ProteinSequence
        or not sequence.sequence
        or not set(sequence.sequence) <= _CANONICAL_AMINO_ACIDS
    ):
        raise ValueError(
            "scoring sequence must contain only canonical amino acids"
        )
    parsed = provider.parse_structure(structure.pdb_string)
    request = _prepare_design_request(
        parsed,
        PROTEINMPNN_MODEL,
        1,
        0.1,
        0.0,
        PROTEINMPNN_SCORING_SEED,
        None,
        sequence.sequence,
    )
    if sequence.residue_ids is not None:
        scoring_layout = ResidueLayout(
            chain_id=",".join(request.structure_chain_order),
            length=len(sequence.residue_ids),
            residue_ids=list(sequence.residue_ids),
        )
        try:
            request = _prepare_design_request(
                parsed,
                PROTEINMPNN_MODEL,
                1,
                0.1,
                0.0,
                PROTEINMPNN_SCORING_SEED,
                ProteinMPNNConstraints(layout=scoring_layout),
                sequence.sequence,
            )
        except ValueError as error:
            raise ValueError(
                "scoring sequence residue layout does not match the parsed "
                "structure layout"
            ) from error
    return request


def validate_scoring_result(raw_result: object) -> float:
    """Validate the provider-native binary32 score without transforming it."""
    binary32_round_trip: float | None = None
    if type(raw_result) is float and math.isfinite(raw_result):
        try:
            binary32_round_trip = struct.unpack(
                "!f",
                struct.pack("!f", raw_result),
            )[0]
        except OverflowError:
            binary32_round_trip = None
    if (
        type(raw_result) is not float
        or not math.isfinite(raw_result)
        or raw_result < 0
        or raw_result > PROTEINMPNN_NATIVE_SCORE_MAXIMUM
        or binary32_round_trip != raw_result
        or (
            raw_result == 0
            and binary32_round_trip is not None
            and math.copysign(1.0, binary32_round_trip)
            != math.copysign(1.0, raw_result)
        )
    ):
        raise RuntimeError(
            "ProteinMPNN provider score is outside the exact native "
            "binary32 non-negative range"
        )
    return raw_result
