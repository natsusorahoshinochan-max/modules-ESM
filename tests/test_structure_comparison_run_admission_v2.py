"""Real-run admission tests for structure-alignment-derived metrics."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackageExecutionResult,
    ModulePackageConformanceError,
    ModulePackagePortCase,
    execute_module_package_case,
    verify_module_package_port,
)
from datatypes.candidate import CandidateCollection
from datatypes.observation import (
    PairwiseObservationContext,
    ScoreCollection,
    ScoreObservation,
)
import modules.structure_comparison.implementation as implementation
from tests.test_structure_comparison_v2 import (
    COLLECTION_OPS_PACKAGE,
    MODULE_PACKAGE,
    SOURCE_PACKAGE,
    STRUCTURE_PREDICTION_PACKAGE,
    TRANSFORM_PACKAGE,
    _ctk_case,
    _inserted_loop_ctk_case,
    _inserted_loop_port_case,
    _three_way_consistency_value,
    _three_way_ctk_case,
)
from tests.test_tm_score_observations_v2 import _evidence


def _execution_cases() -> tuple[ModulePackageContractCase, ...]:
    return (
        _ctk_case(
            case_id="runtime-align-pairs-sequence",
            operation="align_pairs",
            binding_id=(
                "structure_comparison.align_pairs.sequence_primary_affine"
            ),
            pairing_mode="explicit_relation",
        ),
        _ctk_case(
            case_id="runtime-align-pairs-tm",
            operation="align_pairs",
            binding_id=(
                "structure_comparison.align_pairs.structure_first_tm_align"
            ),
            pairing_mode="explicit_relation",
        ),
        _ctk_case(
            case_id="runtime-rmsd-from-alignments",
            operation="rmsd",
            binding_id=(
                "structure_comparison.rmsd_from_alignments."
                "from_alignment_evidence"
            ),
            pairing_mode="explicit_relation",
        ),
        _ctk_case(
            case_id="runtime-tm-score-from-alignments",
            operation="tm_score",
            binding_id=(
                "structure_comparison.tm_score_from_alignments."
                "from_alignment_evidence"
            ),
            pairing_mode="explicit_relation",
        ),
        _three_way_ctk_case(),
        _inserted_loop_ctk_case(),
    )


def _verify_comparison_package(
    tmp_path: Path, case: ModulePackageContractCase
) -> ModulePackageExecutionResult:
    return execute_module_package_case(
        MODULE_PACKAGE,
        case,
        supporting_registrations=(
            TRANSFORM_PACKAGE,
            SOURCE_PACKAGE,
            COLLECTION_OPS_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
        ),
        work_root=tmp_path,
    )


@pytest.mark.parametrize("port_index", range(3))
def test_runtime_alignment_port_conformance(port_index: int) -> None:
    evidence = _evidence()
    ports = (
        ModulePackagePortCase(
            "structure_comparison.alignment_evidence",
            evidence,
            (object(), replace(evidence, correspondence=())),
        ),
        ModulePackagePortCase(
            "structure_comparison.three_way_consistency",
            _three_way_consistency_value(),
            (
                object(),
                replace(_three_way_consistency_value(), classification="all_disagree"),
            ),
        ),
        _inserted_loop_port_case(),
    )
    verify_module_package_port(
        MODULE_PACKAGE,
        ports[port_index],
        supporting_registrations=(
            TRANSFORM_PACKAGE,
            SOURCE_PACKAGE,
            COLLECTION_OPS_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
        ),
    )


@pytest.mark.parametrize("case", _execution_cases(), ids=lambda case: case.case_id)
def test_real_v2_run_admits_exact_structure_alignment_evidence(
    tmp_path: Path, case: ModulePackageContractCase
) -> None:
    result = _verify_comparison_package(tmp_path, case)
    assert result.projection.status == "succeeded"
    if case.node_type_id in {
        "structure_comparison.rmsd_from_alignments",
        "structure_comparison.tm_score_from_alignments",
    }:
        (scores,) = result.outputs["scores"]
        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 2
        assert all(isinstance(entry, ScoreObservation) for entry in scores.entries)
    if case.node_type_id == "structure_comparison.evaluate_inserted_loop":
        (candidates,) = result.outputs["passing_candidates"]
        assert isinstance(candidates, CandidateCollection)
        assert len(candidates.items) == 1
        assert all(
            candidate.candidate_id.startswith("candidate-")
            for candidate in candidates.items
        )


@pytest.mark.parametrize("case", _execution_cases()[2:4], ids=lambda case: case.case_id)
@pytest.mark.parametrize("mutation", ("tampered", "missing"))
def test_real_v2_run_rejects_nonclosed_structure_alignment_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    case: ModulePackageContractCase,
) -> None:
    original = implementation.evidence_metric_context

    def nonclosed_context(*args: Any, **kwargs: Any) -> PairwiseObservationContext:
        context = original(*args, **kwargs)
        if mutation == "tampered":
            return replace(context, evidence_content_digest="sha256:" + "9" * 64)
        return replace(
            context,
            evidence_content_digest=None,
            evidence_method=None,
            subject_axis_content_digest=None,
            reference_axis_content_digest=None,
            normalization_length=None,
            aligned_atom_count=None,
        )

    monkeypatch.setattr(implementation, "evidence_metric_context", nonclosed_context)
    with pytest.raises(
        ModulePackageConformanceError, match="execution did not succeed"
    ):
        _verify_comparison_package(tmp_path, case)
