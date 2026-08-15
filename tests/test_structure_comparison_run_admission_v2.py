"""Real-run admission tests for structure-alignment-derived metrics."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from core import (
    ModulePackageContractCase,
    ModulePackageContractReport,
    ModulePackageConformanceError,
    ModulePackagePortCase,
    verify_module_package_contract,
)
from datatypes import PairwiseObservationContext
from modules.structure_comparison import implementation
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
            case_id="runtime-align-single-sequence",
            operation="align_single",
            binding_id=(
                "structure_comparison.align_single.sequence_primary_affine"
            ),
            pairing_mode=None,
        ),
        _ctk_case(
            case_id="runtime-align-single-tm",
            operation="align_single",
            binding_id=(
                "structure_comparison.align_single.structure_first_tm_align"
            ),
            pairing_mode=None,
        ),
        _ctk_case(
            case_id="runtime-align-fixed",
            operation="align_pairwise",
            binding_id=(
                "structure_comparison.align_fixed_reference."
                "sequence_primary_affine"
            ),
            pairing_mode="fixed_reference",
        ),
        _ctk_case(
            case_id="runtime-align-counterpart",
            operation="align_pairwise",
            binding_id=(
                "structure_comparison.align_counterparts."
                "sequence_primary_affine"
            ),
            pairing_mode="per_subject_counterpart",
        ),
        *tuple(
            _ctk_case(
                case_id=f"runtime-{operation}-{pairing_mode}",
                operation=operation,
                binding_id=(
                    f"structure_comparison.{operation}_{node_suffix}."
                    "from_alignment_evidence"
                ),
                pairing_mode=pairing_mode,
            )
            for operation in ("rmsd", "tm_score")
            for pairing_mode, node_suffix in (
                ("fixed_reference", "fixed_reference"),
                ("per_subject_counterpart", "counterparts"),
            )
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
                "4.0.0",
                evidence,
                (object(), replace(evidence, correspondence=())),
            ),
            ModulePackagePortCase(
                "structure_comparison.three_way_consistency",
                "1.0.0",
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

    assert len(report.case_reports) == 10
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
