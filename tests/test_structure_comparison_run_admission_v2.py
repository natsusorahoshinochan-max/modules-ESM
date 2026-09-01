"""Real-run admission tests for structure-alignment-derived metrics."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackageContractReport,
    ModulePackageConformanceError,
    ModulePackagePortCase,
    verify_module_package_contract,
)
from datatypes.observation import PairwiseObservationContext
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
    tmp_path: Path,
) -> ModulePackageContractReport:
    evidence = _evidence()
    return verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=_execution_cases(),
        port_cases=(
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
                    replace(
                        _three_way_consistency_value(),
                        classification="all_disagree",
                    ),
                ),
            ),
            _inserted_loop_port_case(),
        ),
        supporting_registrations=(
            TRANSFORM_PACKAGE,
            SOURCE_PACKAGE,
            COLLECTION_OPS_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
        ),
        work_root=tmp_path,
    )


def test_real_v2_run_admits_exact_structure_alignment_evidence(
    tmp_path: Path,
) -> None:
    report = _verify_comparison_package(tmp_path)

    assert len(report.case_reports) == 6
    assert {case.status for case in report.case_reports} == {"succeeded"}


@pytest.mark.parametrize("mutation", ("tampered", "missing"))
def test_real_v2_run_rejects_nonclosed_structure_alignment_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    original = implementation.evidence_metric_context

    def nonclosed_context(
        *args: Any,
        **kwargs: Any,
    ) -> PairwiseObservationContext:
        context = original(*args, **kwargs)
        if mutation == "tampered":
            return replace(
                context,
                evidence_content_digest="sha256:" + "9" * 64,
            )
        return replace(
            context,
            evidence_content_digest=None,
            evidence_method=None,
            subject_axis_content_digest=None,
            reference_axis_content_digest=None,
            normalization_length=None,
            aligned_atom_count=None,
        )

    monkeypatch.setattr(
        implementation,
        "evidence_metric_context",
        nonclosed_context,
    )

    with pytest.raises(
        ModulePackageConformanceError,
        match="execution did not succeed",
    ):
        _verify_comparison_package(tmp_path)
