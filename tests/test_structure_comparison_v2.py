"""Focused v3 contracts for resolved-axis structure alignment."""

from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.port_contract import (
    PortValueError,
)
from core.execution.environment import admit_environment_configuration
from core.execution.ledger.projections import RunProjection
from core.run_execution_v2 import V2RunService
from tests.support.result_store import result_store
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackagePortCase,
    verify_module_package_contract,
)
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.scoring.observation_admission import ObservationAdmissionError
from core.workflow.document import WorkflowEdge
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import ScoreCollection
from datatypes.structure import ProteinStructure
from tests.fixtures.observation_admission import (
    admit_test_produced_score_collection,
)
from modules.structure_comparison.alignment import (
    _affine_sequence_alignment,
    align_resolved_axes,
)
from modules.structure_comparison.contracts import (
    INSERTED_LOOP_EVALUATION_METHOD_REFERENCE,
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    SIMPLEFOLD_FOLD_METHOD_REFERENCE,
    STRUCTURE_FIRST_TM_ALIGN_METHOD,
    STRUCTURE_FIRST_TM_ALIGN_METHOD_REFERENCE,
    THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from modules.structure_comparison.domain import (
    AlignmentSegmentMapEntry,
    AtomPairDistanceEvidence,
    InsertedLoopCandidateEvidence,
    InsertedLoopEvaluationCollection,
    InsertedLoopThresholds,
    ResidueIdentityCorrespondence,
    StructureAlignmentEvidence,
    ThreeWayComparisonEdge,
    ThreeWayConfidenceEvidence,
    ThreeWayConsistencyEvidence,
)
from modules.structure_comparison.port_types import (
    ALIGNMENT_EVIDENCE_PORT_TYPE,
    alignment_evidence_from_wire,
    alignment_evidence_to_wire,
)
from modules.structure_comparison.three_way_port import (
    THREE_WAY_CONSISTENCY_PORT_TYPE,
    validate_three_way_consistency,
)
from modules.structure_comparison.inserted_loop_port import (
    INSERTED_LOOP_EVALUATION_PORT_TYPE,
)
from modules.structure_comparison.package import MODULE_PACKAGE
from modules.collection_ops.package import MODULE_PACKAGE as COLLECTION_OPS_PACKAGE
from modules.structure_prediction.package import (
    MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.residue_axis import resolve_residue_axis
from modules.structure_transform.package import MODULE_PACKAGE as TRANSFORM_PACKAGE
from tests.fixtures.structure_comparison_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
    mse_structure_axis_fixture,
)
from tests.fixtures.scientific_operation import (
    admitted_port_fixture,
    build_operation,
    operation_call,
)


_SUBJECT_DIGEST = "sha256:" + "1" * 64
_REFERENCE_DIGEST = "sha256:" + "2" * 64
_AA_1TO3 = {
    "A": "ALA",
    "G": "GLY",
    "M": "MET",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
}


def _multi_segment_structure(
    segments: tuple[
        tuple[str, str, tuple[tuple[float, float, float], ...]],
        ...,
    ],
) -> ProteinStructure:
    lines: list[str] = []
    serial = 1
    for chain_id, sequence, coordinates in segments:
        for residue_number, (amino_acid, coordinate) in enumerate(
            zip(sequence, coordinates, strict=True),
            start=1,
        ):
            x, y, z = coordinate
            line = (
                f"ATOM  {serial:5d}  CA  {_AA_1TO3[amino_acid]} {chain_id}"
                f"{residue_number:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}"
                "  1.00 20.00           C"
            )
            lines.append(line.ljust(80))
            serial += 1
        lines.append("TER")
    return ProteinStructure("\n".join((*lines, "END", "")))


def _axis(
    chain_id: str,
    sequence: str,
    coordinates: tuple[tuple[float, float, float], ...],
):
    return resolve_residue_axis(
        _multi_segment_structure(((chain_id, sequence, coordinates),))
    )


def test_evidence_operations_reuse_the_admitted_structure_axis_identity(
) -> None:
    from core.operation import (
        OperationCall,
    )
    from datatypes.exact_reference import ResidueAxisReference
    from modules.structure_comparison.inserted_loop import _axes_by_subject
    from modules.structure_comparison.three_way import _axis as _three_way_axis
    from modules.structure_transform.port_types import RESOLVED_AXIS_PORT_TYPE

    subject = CandidateDataReference(
        candidate_id="axis-subject",
        data_type_id="protein.structure",
        content_digest="sha256:" + "1" * 64,
    )
    residue_axis = _axis(
        "A",
        "AG",
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    )
    associations = CandidateResolvedResidueAxisAssociations(
        (
            CandidateResolvedResidueAxisAssociation(
                subject,
                residue_axis,
            ),
        )
    )
    admitted_axis = ResidueAxisReference(
        axis_kind="resolved_structure",
        axis_contract=ExactContractReference(
            contract_kind="port_type",
            contract_id=RESOLVED_AXIS_PORT_TYPE.type_id,
            contract_version=RESOLVED_AXIS_PORT_TYPE.version,
            contract_digest=RESOLVED_AXIS_PORT_TYPE.contract_digest,
        ),
        axis_content_digest="sha256:" + "9" * 64,
        source=subject,
        layout=residue_axis.layout,
    )
    admitted = admitted_port_fixture(
        associations,
        port_type_id=(
            "structure_transform."
            "candidate_resolved_residue_axis_associations"
        ),
        value_content_digests=("sha256:" + "2" * 64,),
        scientific_axes=(admitted_axis,),
    )
    call = OperationCall(
        inputs={"axes": admitted},
        node_parameters={},
        binding_parameters={},
        effective_randomness={},
    )

    assert _three_way_axis(call, "axes", subject) == (
        residue_axis,
        admitted_axis,
    )
    assert _axes_by_subject(
        admitted,
        {subject.candidate_id: subject},
    ) == {subject: (residue_axis, admitted_axis)}


def test_sequence_primary_axis_alignment_ignores_coordinate_lure() -> None:
    reference_axis = _axis(
        "R",
        "AAA",
        ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (101.0, 0.0, 0.0)),
    )
    subject_axis = _axis(
        "S",
        "AA",
        ((100.0, 0.0, 0.0), (101.0, 0.0, 0.0)),
    )

    alignment = align_resolved_axes(subject_axis, reference_axis)

    assert alignment.policy.kind == "sequence_primary_affine"
    assert alignment.segment_map[0].cigar == "MMD"
    assert [
        (entry.subject_residue_id, entry.reference_residue_id)
        for entry in alignment.correspondence
    ] == [("S:1", "R:1"), ("S:2", "R:2")]


def test_affine_global_alignment_allows_opposite_terminal_gap_runs() -> None:
    alignment = _affine_sequence_alignment("A", "WW")

    assert alignment.score == -9
    assert alignment.paired_count == 0
    assert alignment.cigar == "DII"


def test_sequence_primary_transform_maps_subject_to_reference() -> None:
    subject_coordinates = (
        (1.0, 2.0, 0.0),
        (3.0, 1.0, 1.0),
        (-1.0, 4.0, 2.0),
    )
    reference_coordinates = (
        (3.0, -1.0, 3.0),
        (4.0, 1.0, 4.0),
        (1.0, -3.0, 5.0),
    )

    alignment = align_resolved_axes(
        _axis("S", "AGS", subject_coordinates),
        _axis("R", "AGS", reference_coordinates),
    )

    assert alignment.transform.maps_from_role == "subject"
    assert alignment.transform.maps_to_role == "reference"
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)
    np.testing.assert_allclose(
        [entry.transformed_subject_coordinate for entry in alignment.correspondence],
        reference_coordinates,
        atol=1e-12,
    )


def test_segment_assignment_resolves_factorial_ambiguity_lexicographically() -> None:
    subject_axis = resolve_residue_axis(
        _multi_segment_structure(
            tuple(
                (chain_id, "A", ((float(index), 0.0, 0.0),))
                for index, chain_id in enumerate("ABCDEFGHI")
            )
        )
    )
    reference_axis = resolve_residue_axis(
        _multi_segment_structure(
            tuple(
                (chain_id, "A", ((float(index), 0.0, 0.0),))
                for index, chain_id in enumerate("123456789")
            )
        )
    )

    alignment = align_resolved_axes(subject_axis, reference_axis)

    assert [
        (entry.subject_segment_index, entry.reference_segment_index)
        for entry in alignment.segment_map
    ] == [(index, index) for index in range(9)]
    assert {entry.cigar for entry in alignment.segment_map} == {"M"}


def test_segment_assignment_lex_order_places_unmatched_after_references() -> None:
    subject_axis = resolve_residue_axis(
        _multi_segment_structure(
            (
                ("A", "A", ((0.0, 0.0, 0.0),)),
                ("B", "A", ((1.0, 0.0, 0.0),)),
                ("C", "A", ((2.0, 0.0, 0.0),)),
            )
        )
    )
    reference_axis = resolve_residue_axis(
        _multi_segment_structure(
            (
                ("R", "A", ((0.0, 0.0, 0.0),)),
                ("S", "A", ((1.0, 0.0, 0.0),)),
            )
        )
    )

    alignment = align_resolved_axes(subject_axis, reference_axis)

    assert [
        (entry.subject_segment_index, entry.reference_segment_index)
        for entry in alignment.segment_map
    ] == [(0, 0), (1, 1)]


def test_affine_alignment_handles_protein_scale_axes_without_recursion() -> None:
    residue_count = 1152
    coordinates = tuple(
        (float(index), float(index % 7), float(index % 11))
        for index in range(residue_count)
    )
    subject_axis = _axis("S", "A" * residue_count, coordinates)
    reference_axis = _axis("R", "A" * residue_count, coordinates)

    alignment = align_resolved_axes(subject_axis, reference_axis)

    assert alignment.segment_map[0].paired_residue_count == residue_count
    assert alignment.segment_map[0].cigar == "M" * residue_count
    assert len(alignment.correspondence) == residue_count


def test_segment_assignment_ignores_chain_ids_unless_explicitly_pinned() -> None:
    subject_axis = resolve_residue_axis(
        _multi_segment_structure(
            (
                (
                    "A",
                    "AAAA",
                    tuple((float(index), 0.0, 0.0) for index in range(4)),
                ),
                (
                    "B",
                    "GGGG",
                    tuple((float(index), 1.0, 0.0) for index in range(4)),
                ),
            )
        )
    )
    reference_axis = resolve_residue_axis(
        _multi_segment_structure(
            (
                (
                    "A",
                    "GGGG",
                    tuple((float(index), 1.0, 0.0) for index in range(4)),
                ),
                (
                    "B",
                    "AAAA",
                    tuple((float(index), 0.0, 0.0) for index in range(4)),
                ),
            )
        )
    )

    unpinned = align_resolved_axes(subject_axis, reference_axis)
    pinned = align_resolved_axes(
        subject_axis,
        reference_axis,
        pin_matching_chain_ids=True,
    )

    assert [
        (entry.subject_segment_index, entry.reference_segment_index)
        for entry in unpinned.segment_map
    ] == [(0, 1), (1, 0)]
    assert [
        (entry.subject_segment_index, entry.reference_segment_index)
        for entry in pinned.segment_map
    ] == [(0, 0), (1, 1)]


def test_explicit_chain_pinning_rejects_duplicate_chain_names() -> None:
    axis = resolve_residue_axis(
        _multi_segment_structure(
            (
                ("A", "A", ((0.0, 0.0, 0.0),)),
                ("B", "G", ((1.0, 0.0, 0.0),)),
            )
        )
    )
    duplicated = replace(
        axis,
        segments=(
            axis.segments[0],
            replace(axis.segments[1], chain_id="A"),
        ),
    )

    with pytest.raises(ValueError, match="duplicate chain_id"):
        align_resolved_axes(
            duplicated,
            axis,
            pin_matching_chain_ids=True,
        )


def test_alignment_consumes_normalized_mse_axis_without_reparsing_pdb() -> None:
    subject_axis = resolve_residue_axis(mse_structure_axis_fixture())
    reference_axis = _axis("R", "M", ((7.0, 8.0, 9.0),))

    alignment = align_resolved_axes(subject_axis, reference_axis)

    assert subject_axis.residue_names == ("MET",)
    assert alignment.segment_map[0].cigar == "M"
    assert alignment.correspondence[0].subject_coordinate == (7.0, 8.0, 9.0)
    assert alignment.correspondence[0].subject_residue_id == "A:1"


def test_structure_first_tm_align_uses_axis_values_and_no_seed_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinates = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    subject_axis = _axis("S", "AAA", coordinates)
    reference_axis = _axis("R", "AAA", coordinates)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class Result:
        seqxA = "AAA"
        seqyA = "AAA"
        u = np.eye(3)
        t = np.zeros(3)

    def fake_tm_align(*args: object, **kwargs: object) -> Result:
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(
        "modules.structure_comparison.alignment.tm_align",
        fake_tm_align,
    )

    alignment = align_resolved_axes(
        subject_axis,
        reference_axis,
        correspondence_method="structure_first_tm_align",
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert len(args) == 4
    np.testing.assert_array_equal(args[0], np.asarray(coordinates))
    np.testing.assert_array_equal(args[1], np.asarray(coordinates))
    assert args[2:] == ("AAA", "AAA")
    assert kwargs == {"alignment": None}
    assert alignment.policy.kind == "structure_first_tm_align"


def test_structure_first_tm_align_honors_explicit_single_segment_chain_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    axis = _axis(
        "A",
        "AGS",
        ((0.0, 0.0, 0.0), (1.0, 2.0, 0.0), (2.0, 0.0, 3.0)),
    )

    class Result:
        seqxA = "AGS"
        seqyA = "AGS"
        u = np.eye(3)
        t = np.zeros(3)

    monkeypatch.setattr(
        "modules.structure_comparison.alignment.tm_align",
        lambda *args, **kwargs: Result(),
    )

    alignment = align_resolved_axes(
        axis,
        axis,
        correspondence_method="structure_first_tm_align",
        pin_matching_chain_ids=True,
    )

    assert alignment.policy.pin_matching_chain_ids is True


def test_structure_first_tm_align_translates_documented_transform_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject_coordinates = (
        (1.0, 2.0, 0.0),
        (3.0, 1.0, 1.0),
        (-1.0, 4.0, 2.0),
    )
    reference_coordinates = (
        (3.0, -1.0, 3.0),
        (4.0, 1.0, 4.0),
        (1.0, -3.0, 5.0),
    )

    class Result:
        seqxA = "AGS"
        seqyA = "AGS"
        u = np.asarray(
            (
                (0.0, -1.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0),
            )
        )
        t = np.asarray((5.0, -2.0, 3.0))

    monkeypatch.setattr(
        "modules.structure_comparison.alignment.tm_align",
        lambda *args, **kwargs: Result(),
    )

    alignment = align_resolved_axes(
        _axis("S", "AGS", subject_coordinates),
        _axis("R", "AGS", reference_coordinates),
        correspondence_method="structure_first_tm_align",
    )

    assert alignment.transform.maps_from_role == "subject"
    assert alignment.transform.maps_to_role == "reference"
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)
    np.testing.assert_allclose(
        [entry.transformed_subject_coordinate for entry in alignment.correspondence],
        reference_coordinates,
        atol=1e-12,
    )


def test_structure_first_tm_align_propagates_engine_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    axis = _axis("A", "AAA", ((0.0, 0.0, 0.0),) * 3)

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("tm-align-failed")

    monkeypatch.setattr(
        "modules.structure_comparison.alignment.tm_align",
        fail,
    )

    with pytest.raises(RuntimeError, match="tm-align-failed"):
        align_resolved_axes(
            axis,
            axis,
            correspondence_method="structure_first_tm_align",
        )


def test_v3_alignment_methods_publish_exact_nonfallback_algorithms() -> None:
    sequence = SEQUENCE_PRIMARY_AFFINE_METHOD.algorithm_identity
    tm_method = STRUCTURE_FIRST_TM_ALIGN_METHOD.algorithm_identity

    assert sequence["residue_correspondence"]["integer_scale"] == 2
    assert sequence["residue_correspondence"]["gap_open"] == -6
    assert sequence["residue_correspondence"]["terminal_gap_open"] == -4
    assert sequence["residue_correspondence"]["enumerates_alignments"] is False
    assert sequence["segment_assignment"]["threshold"] is None
    assert sequence["segment_assignment"]["enumerates_assignments"] is False
    assert tm_method["seed_alignment"] is None
    assert tm_method["fallback"] is None
    assert "alignment=None" in tm_method["engine_call"]


def test_v5_alignment_evidence_codec_carries_axis_provenance_and_counts() -> None:
    subject_axis = _axis("S", "AA", ((1.0, 0.0, 0.0), (2.0, 0.0, 0.0)))
    reference_axis = _axis("R", "AA", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    resolved = align_resolved_axes(subject_axis, reference_axis)
    evidence = StructureAlignmentEvidence(
        subject=CandidateDataReference(
            candidate_id="subject-a",
            data_type_id="protein.structure",
            content_digest=_SUBJECT_DIGEST,
        ),
        reference=CandidateDataReference(
            candidate_id="reference-a",
            data_type_id="protein.structure",
            content_digest=_REFERENCE_DIGEST,
        ),
        subject_axis_content_digest="sha256:" + "3" * 64,
        reference_axis_content_digest="sha256:" + "4" * 64,
        segment_map=resolved.segment_map,
        policy=resolved.policy,
        correspondence=resolved.correspondence,
        transform=resolved.transform,
        normalization=resolved.normalization,
        rmsd=resolved.rmsd,
        coverage=resolved.coverage,
        method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    )

    wire = alignment_evidence_to_wire(evidence)

    assert wire["schema_version"] == "5.0.0"
    assert wire["subject"] == {
        "candidate_id": "subject-a",
        "data_type_id": "protein.structure",
        "content_digest": _SUBJECT_DIGEST,
    }
    assert wire["subject_axis_content_digest"] == "sha256:" + "3" * 64
    assert wire["reference_axis_content_digest"] == "sha256:" + "4" * 64
    assert wire["segment_map"][0]["cigar"] == "MM"
    assert wire["policy"] == {
        "kind": "sequence_primary_affine",
        "pin_matching_chain_ids": False,
    }
    assert wire["normalization"] == {
        "subject_axis_residue_count": 2,
        "reference_axis_residue_count": 2,
        "subject_ca_count": 2,
        "reference_ca_count": 2,
        "aligned_atom_count": 2,
    }
    assert alignment_evidence_from_wire(wire) == evidence

    impossible = replace(
        evidence,
        segment_map=(
            replace(
                evidence.segment_map[0],
                paired_residue_count=1,
                cigar="MD",
            ),
        ),
    )
    with pytest.raises(ValueError, match="sequence-paired residue count"):
        ALIGNMENT_EVIDENCE_PORT_TYPE.encode(impossible)


def test_alignment_evidence_accepts_zero_pair_segment_with_global_ca_fit() -> None:
    subject_axis = resolve_residue_axis(
        _multi_segment_structure(
            (
                ("S", "WW", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))),
                ("T", "A", ((2.0, 0.0, 0.0),)),
            )
        )
    )
    reference_axis = resolve_residue_axis(
        _multi_segment_structure(
            (
                ("R", "A", ((0.0, 1.0, 0.0),)),
                ("Q", "A", ((2.0, 1.0, 0.0),)),
            )
        )
    )
    resolved = align_resolved_axes(subject_axis, reference_axis)
    evidence = StructureAlignmentEvidence(
        subject=CandidateDataReference(
            candidate_id="subject-a",
            data_type_id="protein.structure",
            content_digest=_SUBJECT_DIGEST,
        ),
        reference=CandidateDataReference(
            candidate_id="reference-a",
            data_type_id="protein.structure",
            content_digest=_REFERENCE_DIGEST,
        ),
        subject_axis_content_digest="sha256:" + "3" * 64,
        reference_axis_content_digest="sha256:" + "4" * 64,
        segment_map=resolved.segment_map,
        policy=resolved.policy,
        correspondence=resolved.correspondence,
        transform=resolved.transform,
        normalization=resolved.normalization,
        rmsd=resolved.rmsd,
        coverage=resolved.coverage,
        method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    )

    encoded = ALIGNMENT_EVIDENCE_PORT_TYPE.encode(evidence)

    assert [
        (entry.cigar, entry.paired_residue_count)
        for entry in evidence.segment_map
    ] == [("DII", 0), ("M", 1)]
    assert evidence.normalization.aligned_atom_count == 1
    assert ALIGNMENT_EVIDENCE_PORT_TYPE.decode(encoded) == evidence


class _RunResources:
    @contextmanager
    def engine_invocation(self, **details: object):
        del details
        yield "invocation"


class _CountingRunResources:
    def __init__(self) -> None:
        self.invocations = 0

    @contextmanager
    def engine_invocation(self, **details: object):
        del details
        self.invocations += 1
        yield "invocation"


def _candidate_reference(
    candidate_id: str,
    structure: ProteinStructure,
) -> CandidateDataReference:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
    return CandidateDataReference(
        candidate_id=candidate_id,
        data_type_id="protein.structure",
        content_digest=port_type.content_digest(structure),
    )


def test_alignment_rejects_stale_axis_reference_before_engine_start() -> None:
    catalog = build_frozen_catalog((TRANSFORM_PACKAGE, MODULE_PACKAGE))
    subject_structure = _multi_segment_structure(
        (("S", "AG", ((1.0, 2.0, 0.0), (3.0, 1.0, 1.0))),)
    )
    reference_structure = _multi_segment_structure(
        (("R", "AG", ((3.0, -1.0, 3.0), (4.0, 1.0, 4.0))),)
    )
    subject_reference = _candidate_reference("subject", subject_structure)
    reference_reference = _candidate_reference("reference", reference_structure)
    subjects = CandidateCollection(
        collection_id="subjects",
        item_type="protein.structure",
        items=(Candidate("subject", subject_structure),),
    )
    references = CandidateCollection(
        collection_id="references",
        item_type="protein.structure",
        items=(Candidate("reference", reference_structure),),
    )
    subject_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=replace(
                    subject_reference,
                    content_digest="sha256:" + "9" * 64,
                ),
                residue_axis=resolve_residue_axis(subject_structure),
            ),
        )
    )
    reference_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=reference_reference,
                residue_axis=resolve_residue_axis(reference_structure),
            ),
        )
    )
    resources = _CountingRunResources()
    binding_id = "structure_comparison.align_single.sequence_primary_affine"
    build_operation(
        catalog,
        binding_id,
        resources,
        binding_version="5.0.0",
    )
    with pytest.raises(ValueError, match="structure content digest"):
        operation_call(
            catalog=catalog,
            binding_id=binding_id,
            binding_version="5.0.0",
            inputs={
                "subjects": subjects,
                "subject_residue_axes": subject_axes,
                "references": references,
                "reference_residue_axes": reference_axes,
            },
            node_parameters={"pin_matching_chain_ids": False},
            binding_parameters={},
        )

    assert resources.invocations == 0


def test_v5_alignment_and_v6_metric_preserve_admitted_references() -> None:
    catalog = build_frozen_catalog((TRANSFORM_PACKAGE, MODULE_PACKAGE))
    reference_structure = _multi_segment_structure(
        (("R", "AA", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))),)
    )
    alpha_structure = _multi_segment_structure(
        (("A", "AA", ((2.0, 0.0, 0.0), (3.0, 0.0, 0.0))),)
    )
    zeta_structure = _multi_segment_structure(
        (("Z", "AA", ((5.0, 0.0, 0.0), (6.0, 0.0, 0.0))),)
    )
    alpha_reference = _candidate_reference("alpha", alpha_structure)
    zeta_reference = _candidate_reference("zeta", zeta_structure)
    fixed_reference = _candidate_reference("fixed", reference_structure)
    subjects = CandidateCollection(
        collection_id="subjects",
        item_type="protein.structure",
        items=(
            Candidate("zeta", zeta_structure),
            Candidate("alpha", alpha_structure),
        ),
    )
    references = CandidateCollection(
        collection_id="references",
        item_type="protein.structure",
        items=(Candidate("fixed", reference_structure),),
    )
    subject_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=zeta_reference,
                residue_axis=resolve_residue_axis(zeta_structure),
            ),
            CandidateResolvedResidueAxisAssociation(
                subject=alpha_reference,
                residue_axis=resolve_residue_axis(alpha_structure),
            ),
        )
    )
    reference_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=fixed_reference,
                residue_axis=resolve_residue_axis(reference_structure),
            ),
        )
    )
    alignment_binding = (
        "structure_comparison.align_fixed_reference.sequence_primary_affine"
    )
    aligner = build_operation(
        catalog,
        alignment_binding,
        _RunResources(),
        binding_version="5.0.0",
    )
    call = operation_call(
        catalog=catalog,
        binding_id=alignment_binding,
        binding_version="5.0.0",
        inputs={
            "subjects": subjects,
            "subject_residue_axes": subject_axes,
            "references": references,
            "reference_residue_axes": reference_axes,
        },
        node_parameters={"pin_matching_chain_ids": False},
        binding_parameters={},
    )
    subject_axis_port = call.inputs["subject_residue_axes"]
    trusted_subject_axes = tuple(
        replace(
            axis,
            axis_content_digest="sha256:" + symbol * 64,
        )
        for axis, symbol in zip(
            subject_axis_port.scientific_axes,
            ("8", "9"),
            strict=True,
        )
    )
    reference_axis_port = call.inputs["reference_residue_axes"]
    trusted_reference_axis = replace(
        reference_axis_port.scientific_axes[0],
        axis_content_digest="sha256:" + "7" * 64,
    )
    call = replace(
        call,
        inputs={
            **call.inputs,
            "subject_residue_axes": replace(
                subject_axis_port,
                values=(
                    replace(
                        subject_axis_port.values[0],
                        scientific_axes=trusted_subject_axes,
                    ),
                ),
            ),
            "reference_residue_axes": replace(
                reference_axis_port,
                values=(
                    replace(
                        reference_axis_port.values[0],
                        scientific_axes=(trusted_reference_axis,),
                    ),
                ),
            ),
        },
    )

    aligned = aligner.execute(call)["alignments"]

    assert [entry.subject.candidate_id for entry in aligned] == [
        "alpha",
        "zeta",
    ]
    assert all(entry.reference.candidate_id == "fixed" for entry in aligned)
    trusted_subject_digests = {
        axis.source: axis.axis_content_digest
        for axis in trusted_subject_axes
    }
    assert {
        entry.subject: entry.subject_axis_content_digest
        for entry in aligned
    } == trusted_subject_digests
    assert {
        entry.reference_axis_content_digest for entry in aligned
    } == {trusted_reference_axis.axis_content_digest}
    assert all(
        ALIGNMENT_EVIDENCE_PORT_TYPE.decode(
            ALIGNMENT_EVIDENCE_PORT_TYPE.encode(entry)
        )
        == entry
        for entry in aligned
    )

    metric_binding = (
        "structure_comparison.tm_score_fixed_reference."
        "from_alignment_evidence"
    )
    scorer = build_operation(
        catalog,
        metric_binding,
        _RunResources(),
        binding_version="6.0.0",
    )
    observed = scorer.execute(
        operation_call(
            catalog=catalog,
            binding_id=metric_binding,
            binding_version="6.0.0",
            inputs={
                "alignments": aligned,
                "subjects": subjects,
                "references": references,
            },
            node_parameters={},
            binding_parameters={},
        )
    )["scores"]

    assert type(observed) is ScoreCollection
    assert [entry.subject for entry in observed.entries] == [
        alpha_reference,
        zeta_reference,
    ]
    assert [entry.value for entry in observed.entries] == [1.0, 1.0]
    assert all(entry.residue_axis is None for entry in observed.entries)
    assert all(
        entry.context.subject.candidate == entry.subject
        and entry.context.reference.candidate == fixed_reference
        for entry in observed.entries
    )
    assert all(
        entry.context.evidence_method
        == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
        for entry in observed.entries
    )

    metric_contract = catalog.require_contract(
        "binding",
        metric_binding,
        "6.0.0",
    )
    metric_inputs = {
        "alignments": aligned,
        "subjects": subjects,
        "references": references,
    }
    admit_test_produced_score_collection(
        catalog=catalog,
        binding=metric_contract,
        output_port="scores",
        collection=observed,
        inputs=metric_inputs,
        outputs={"scores": observed},
    )

    provenance_conflicts = (
        {"evidence_content_digest": "sha256:" + "9" * 64},
        {"subject_axis_content_digest": "sha256:" + "6" * 64},
        {"reference_axis_content_digest": "sha256:" + "5" * 64},
        {"evidence_method": STRUCTURE_FIRST_TM_ALIGN_METHOD_REFERENCE},
        {"normalization_length": 3},
        {"aligned_atom_count": 1},
        {
            "subject_axis_content_digest": None,
            "reference_axis_content_digest": None,
        },
        {
            "evidence_content_digest": None,
            "evidence_method": None,
            "subject_axis_content_digest": None,
            "reference_axis_content_digest": None,
            "normalization_length": None,
            "aligned_atom_count": None,
        },
    )
    for conflict in provenance_conflicts:
        first = observed.entries[0]
        tampered = replace(
            observed,
            entries=(
                replace(first, context=replace(first.context, **conflict)),
                *observed.entries[1:],
            ),
        )
        with pytest.raises(
            ObservationAdmissionError,
            match="alignment evidence provenance",
        ):
            admit_test_produced_score_collection(
                catalog=catalog,
                binding=metric_contract,
                output_port="scores",
                collection=tampered,
                inputs=metric_inputs,
                outputs={"scores": tampered},
            )


def test_structure_comparison_catalog_has_only_active_split_paths() -> None:
    catalog = build_frozen_catalog((TRANSFORM_PACKAGE, MODULE_PACKAGE))
    contracts = [
        contract
        for contract in catalog.contracts
        if contract.contract_id.startswith("structure_comparison.")
    ]

    assert contracts
    assert {
        (contract.contract_id, contract.contract_version)
        for contract in contracts
        if contract.contract_kind == "node_type"
    } == {
        ("structure_comparison.align_single", "5.0.0"),
        ("structure_comparison.align_fixed_reference", "5.0.0"),
        ("structure_comparison.align_counterparts", "5.0.0"),
        ("structure_comparison.evaluate_inserted_loop", "2.0.0"),
        (
            "structure_comparison.classify_three_way_consistency",
            "3.0.0",
        ),
        ("structure_comparison.rmsd_fixed_reference", "6.0.0"),
        ("structure_comparison.rmsd_counterparts", "6.0.0"),
        ("structure_comparison.tm_score_fixed_reference", "6.0.0"),
        ("structure_comparison.tm_score_counterparts", "6.0.0"),
    }
    assert {
        contract.contract_version
        for contract in contracts
        if contract.contract_kind in {"method", "metric", "utility_transform"}
    } == {"2.0.0", "3.0.0", "4.0.0"}
    assert {
        (contract.contract_id, contract.contract_version)
        for contract in contracts
        if contract.contract_kind == "binding"
    } == {
        (
            "structure_comparison.align_single.sequence_primary_affine",
            "5.0.0",
        ),
        (
            "structure_comparison.align_single.structure_first_tm_align",
            "5.0.0",
        ),
        (
            "structure_comparison.align_fixed_reference."
            "sequence_primary_affine",
            "5.0.0",
        ),
        (
            "structure_comparison.align_counterparts."
            "sequence_primary_affine",
            "5.0.0",
        ),
        (
            "structure_comparison.classify_three_way_consistency.direct",
            "3.0.0",
        ),
        (
            "structure_comparison.evaluate_inserted_loop.direct",
            "2.0.0",
        ),
        (
            "structure_comparison.rmsd_fixed_reference."
            "from_alignment_evidence",
            "6.0.0",
        ),
        (
            "structure_comparison.rmsd_counterparts."
            "from_alignment_evidence",
            "6.0.0",
        ),
        (
            "structure_comparison.tm_score_fixed_reference."
            "from_alignment_evidence",
            "6.0.0",
        ),
        (
            "structure_comparison.tm_score_counterparts."
            "from_alignment_evidence",
            "6.0.0",
        ),
    }
    node_ids = {
        contract.contract_id
        for contract in contracts
        if contract.contract_kind == "node_type"
    }
    assert node_ids == {
        "structure_comparison.align_single",
        "structure_comparison.align_fixed_reference",
        "structure_comparison.align_counterparts",
        "structure_comparison.classify_three_way_consistency",
        "structure_comparison.evaluate_inserted_loop",
        "structure_comparison.rmsd_fixed_reference",
        "structure_comparison.rmsd_counterparts",
        "structure_comparison.tm_score_fixed_reference",
        "structure_comparison.tm_score_counterparts",
    }
    for operation in ("align", "rmsd", "tm_score"):
        operation_version = "5.0.0" if operation == "align" else "6.0.0"
        fixed_name = (
            "align_fixed_reference"
            if operation == "align"
            else f"{operation}_fixed_reference"
        )
        counterpart_name = (
            "align_counterparts"
            if operation == "align"
            else f"{operation}_counterparts"
        )
        fixed = catalog.require_contract(
            "node_type",
            f"structure_comparison.{fixed_name}",
            operation_version,
        )
        counterparts = catalog.require_contract(
            "node_type",
            f"structure_comparison.{counterpart_name}",
            operation_version,
        )
        assert "pairing" not in {
            item["name"] for item in fixed.descriptor["inputs"]
        }
        pairing = {
            item["name"]: item
            for item in counterparts.descriptor["inputs"]
        }["pairing"]
        assert pairing["required"] is True
        if operation != "align":
            for node in (fixed, counterparts):
                scores = next(
                    item
                    for item in node.descriptor["outputs"]
                    if item["name"] == "scores"
                )
                assert scores["port_type"]["contract_version"] == "5.0.0"
    score_bindings = [
        contract
        for contract in contracts
        if contract.contract_kind == "binding"
        and contract.contract_version == "6.0.0"
    ]
    assert all(
        declaration["axis_direction"] is None
        and declaration["axis_port"] is None
        and declaration["guaranteed_multiplicity"] == "one"
        for binding in score_bindings
        for declaration in binding.descriptor["produced_observations"]
    )
    assert {
        contract.contract_id
        for contract in contracts
        if contract.contract_id.endswith(".direct")
    } == {
        "structure_comparison.classify_three_way_consistency.direct",
        "structure_comparison.evaluate_inserted_loop.direct",
    }
    assert not any(
        "batch_tm_score" in contract.contract_id for contract in contracts
    )


def _source_node(scenario: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_comparison_source",
        node_type_version="5.0.0",
        binding_id="contract_test.structure_comparison_source.fixture",
        binding_version="5.0.0",
        node_parameters={"scenario": scenario},
        binding_parameters={},
    )


def _axis_node(node_id: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=node_id,
        node_type_id="structure_transform.resolve_candidate_residue_axes",
        node_type_version="6.0.0",
        binding_id="structure_transform.resolve_candidate_residue_axes.direct",
        binding_version="6.0.0",
        node_parameters={},
        binding_parameters={},
    )


def _axis_edges() -> tuple[WorkflowEdge, ...]:
    return (
        WorkflowEdge(
            "source",
            "subjects",
            "subject-axis",
            "structure_candidates",
        ),
        WorkflowEdge(
            "source",
            "references",
            "reference-axis",
            "structure_candidates",
        ),
    )


def _alignment_edges(target_node_id: str) -> tuple[WorkflowEdge, ...]:
    return (
        WorkflowEdge("source", "subjects", target_node_id, "subjects"),
        WorkflowEdge(
            "subject-axis",
            "residue_axes",
            target_node_id,
            "subject_residue_axes",
        ),
        WorkflowEdge("source", "references", target_node_id, "references"),
        WorkflowEdge(
            "reference-axis",
            "residue_axes",
            target_node_id,
            "reference_residue_axes",
        ),
    )


def _ctk_case(
    *,
    case_id: str,
    operation: str,
    binding_id: str,
    pairing_mode: str | None,
) -> ModulePackageContractCase:
    contract_version = (
        "5.0.0"
        if operation in {"align_single", "align_pairwise"}
        else "6.0.0"
    )
    scenario = (
        "single"
        if operation == "align_single"
        else "fixed_reference"
        if pairing_mode == "fixed_reference"
        else "per_subject_counterpart"
    )
    source = _source_node(scenario)
    axis_nodes = (_axis_node("subject-axis"), _axis_node("reference-axis"))
    node_name = (
        "align_single"
        if operation == "align_single"
        else "align_fixed_reference"
        if operation == "align_pairwise" and pairing_mode == "fixed_reference"
        else "align_counterparts"
        if operation == "align_pairwise"
        else f"{operation}_fixed_reference"
        if pairing_mode == "fixed_reference"
        else f"{operation}_counterparts"
    )
    if operation in {"align_single", "align_pairwise"}:
        edges = (*_axis_edges(), *_alignment_edges("contract-test-node"))
        if pairing_mode == "per_subject_counterpart":
            edges = (
                *edges,
                WorkflowEdge(
                    "source",
                    "pairing",
                    "contract-test-node",
                    "pairing",
                ),
            )
        workflow_nodes = (source, *axis_nodes)
        expected_observations: dict[str, int] = {}
        node_parameters = {"pin_matching_chain_ids": False}
    else:
        alignment_node_name = (
            "align_fixed_reference"
            if pairing_mode == "fixed_reference"
            else "align_counterparts"
        )
        alignment_binding = (
            f"structure_comparison.{alignment_node_name}."
            "sequence_primary_affine"
        )
        alignment = WorkflowNodeInstance(
            node_id="alignment",
            node_type_id=f"structure_comparison.{alignment_node_name}",
            node_type_version="5.0.0",
            binding_id=alignment_binding,
            binding_version="5.0.0",
            node_parameters={"pin_matching_chain_ids": False},
            binding_parameters={},
        )
        edges = (
            *_axis_edges(),
            *_alignment_edges("alignment"),
            WorkflowEdge(
                "alignment",
                "alignments",
                "contract-test-node",
                "alignments",
            ),
            WorkflowEdge(
                "source",
                "subjects",
                "contract-test-node",
                "subjects",
            ),
            WorkflowEdge(
                "source",
                "references",
                "contract-test-node",
                "references",
            ),
        )
        if pairing_mode == "per_subject_counterpart":
            edges = (
                *edges,
                WorkflowEdge("source", "pairing", "alignment", "pairing"),
                WorkflowEdge(
                    "source",
                    "pairing",
                    "contract-test-node",
                    "pairing",
                ),
            )
        workflow_nodes = (source, *axis_nodes, alignment)
        expected_observations = {"scores": 2}
        node_parameters = {}
    return ModulePackageContractCase(
        case_id=case_id,
        node_type_id=f"structure_comparison.{node_name}",
        node_type_version=contract_version,
        binding_id=binding_id,
        binding_version=contract_version,
        node_parameters=node_parameters,
        binding_parameters={},
        environment_values={},
        workflow_nodes=workflow_nodes,
        workflow_edges=edges,
        expected_observation_counts=expected_observations,
    )


def _three_way_node(
    node_id: str,
    node_type_id: str,
    node_type_version: str,
    binding_id: str,
    binding_version: str,
) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=node_id,
        node_type_id=node_type_id,
        node_type_version=node_type_version,
        binding_id=binding_id,
        binding_version=binding_version,
        node_parameters=(
            {"pin_matching_chain_ids": False}
            if node_type_id.startswith("structure_comparison.align_")
            else {}
        ),
        binding_parameters={},
    )


def _inserted_loop_ctk_case(
    *,
    missing_loop_plddt: bool = False,
    confidence_binding_id: str = (
        "contract_test.inserted_loop_confidence_source.fixture"
    ),
) -> ModulePackageContractCase:
    def operation_node(
        node_id: str,
        node_type_id: str,
        version: str,
        binding_id: str,
        parameters: dict[str, object] | None = None,
    ) -> WorkflowNodeInstance:
        return WorkflowNodeInstance(
            node_id=node_id,
            node_type_id=node_type_id,
            node_type_version=version,
            binding_id=binding_id,
            binding_version=version,
            node_parameters=parameters or {},
            binding_parameters={},
        )

    source = operation_node(
        "loop-source",
        "contract_test.inserted_loop_source",
        "5.0.0",
        "contract_test.inserted_loop_source.fixture",
    )
    subject_axis = operation_node(
        "loop-subject-axis",
        "structure_transform.resolve_candidate_residue_axes",
        "6.0.0",
        "structure_transform.resolve_candidate_residue_axes.direct",
    )
    reference_axis = replace(subject_axis, node_id="loop-reference-axis")
    counterpart_axis = replace(subject_axis, node_id="loop-counterpart-axis")
    core_alignment = operation_node(
        "loop-core-alignment",
        "structure_comparison.align_fixed_reference",
        "5.0.0",
        "structure_comparison.align_fixed_reference.sequence_primary_affine",
        {"pin_matching_chain_ids": False},
    )
    core_tm = operation_node(
        "loop-core-tm",
        "structure_comparison.tm_score_fixed_reference",
        "6.0.0",
        "structure_comparison.tm_score_fixed_reference.from_alignment_evidence",
    )
    core_rmsd = operation_node(
        "loop-core-rmsd",
        "structure_comparison.rmsd_fixed_reference",
        "6.0.0",
        "structure_comparison.rmsd_fixed_reference.from_alignment_evidence",
    )
    counterpart_alignment = operation_node(
        "loop-counterpart-alignment",
        "structure_comparison.align_counterparts",
        "5.0.0",
        "structure_comparison.align_counterparts.sequence_primary_affine",
        {"pin_matching_chain_ids": False},
    )
    counterpart_tm = operation_node(
        "loop-counterpart-tm",
        "structure_comparison.tm_score_counterparts",
        "6.0.0",
        "structure_comparison.tm_score_counterparts.from_alignment_evidence",
    )
    counterpart_rmsd = operation_node(
        "loop-counterpart-rmsd",
        "structure_comparison.rmsd_counterparts",
        "6.0.0",
        "structure_comparison.rmsd_counterparts.from_alignment_evidence",
    )
    prediction_axis = operation_node(
        "loop-prediction-axis",
        "contract_test.prediction_axis_source",
        "5.0.0",
        "contract_test.prediction_axis_source.fixture",
    )
    confidence_facts = operation_node(
        "loop-confidence-facts",
        "contract_test.prediction_confidence_fact_source",
        "5.0.0",
        "contract_test.esmfold2_confidence_fact_source.fixture",
        {"missing_loop_plddt": missing_loop_plddt},
    )
    confidence = operation_node(
        "loop-confidence",
        "contract_test.prediction_confidence_source",
        "5.0.0",
        confidence_binding_id,
    )
    edges = (
        WorkflowEdge("loop-source", "subjects", "loop-subject-axis", "structure_candidates"),
        WorkflowEdge("loop-source", "references", "loop-reference-axis", "structure_candidates"),
        WorkflowEdge("loop-source", "counterparts", "loop-counterpart-axis", "structure_candidates"),
        WorkflowEdge("loop-source", "subjects", "loop-core-alignment", "subjects"),
        WorkflowEdge("loop-subject-axis", "residue_axes", "loop-core-alignment", "subject_residue_axes"),
        WorkflowEdge("loop-source", "references", "loop-core-alignment", "references"),
        WorkflowEdge("loop-reference-axis", "residue_axes", "loop-core-alignment", "reference_residue_axes"),
        WorkflowEdge("loop-core-alignment", "alignments", "loop-core-tm", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-core-tm", "subjects"),
        WorkflowEdge("loop-source", "references", "loop-core-tm", "references"),
        WorkflowEdge("loop-core-alignment", "alignments", "loop-core-rmsd", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-core-rmsd", "subjects"),
        WorkflowEdge("loop-source", "references", "loop-core-rmsd", "references"),
        WorkflowEdge("loop-source", "subjects", "loop-counterpart-alignment", "subjects"),
        WorkflowEdge("loop-subject-axis", "residue_axes", "loop-counterpart-alignment", "subject_residue_axes"),
        WorkflowEdge("loop-source", "counterparts", "loop-counterpart-alignment", "references"),
        WorkflowEdge("loop-counterpart-axis", "residue_axes", "loop-counterpart-alignment", "reference_residue_axes"),
        WorkflowEdge("loop-source", "pairing", "loop-counterpart-alignment", "pairing"),
        WorkflowEdge("loop-counterpart-alignment", "alignments", "loop-counterpart-tm", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-counterpart-tm", "subjects"),
        WorkflowEdge("loop-source", "counterparts", "loop-counterpart-tm", "references"),
        WorkflowEdge("loop-source", "pairing", "loop-counterpart-tm", "pairing"),
        WorkflowEdge("loop-counterpart-alignment", "alignments", "loop-counterpart-rmsd", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-counterpart-rmsd", "subjects"),
        WorkflowEdge("loop-source", "counterparts", "loop-counterpart-rmsd", "references"),
        WorkflowEdge("loop-source", "pairing", "loop-counterpart-rmsd", "pairing"),
        WorkflowEdge("loop-source", "sequence_parents", "loop-prediction-axis", "sequence_parents"),
        WorkflowEdge("loop-source", "subjects", "loop-confidence-facts", "structures"),
        WorkflowEdge("loop-prediction-axis", "prediction_axis", "loop-confidence-facts", "prediction_axis"),
        WorkflowEdge("loop-source", "subjects", "loop-confidence", "structures"),
        WorkflowEdge("loop-confidence-facts", "confidence_facts", "loop-confidence", "confidence_facts"),
        WorkflowEdge("loop-source", "subjects", "contract-test-node", "subjects"),
        WorkflowEdge("loop-subject-axis", "residue_axes", "contract-test-node", "subject_residue_axes"),
        WorkflowEdge("loop-source", "references", "contract-test-node", "references"),
        WorkflowEdge("loop-source", "counterparts", "contract-test-node", "counterparts"),
        WorkflowEdge("loop-source", "pairing", "contract-test-node", "counterpart_pairing"),
        WorkflowEdge("loop-core-alignment", "alignments", "contract-test-node", "resolved_core_alignments"),
        WorkflowEdge("loop-core-tm", "scores", "contract-test-node", "resolved_core_tm_scores"),
        WorkflowEdge("loop-core-rmsd", "scores", "contract-test-node", "resolved_core_rmsd_scores"),
        WorkflowEdge("loop-counterpart-alignment", "alignments", "contract-test-node", "counterpart_alignments"),
        WorkflowEdge("loop-counterpart-tm", "scores", "contract-test-node", "counterpart_tm_scores"),
        WorkflowEdge("loop-counterpart-rmsd", "scores", "contract-test-node", "counterpart_rmsd_scores"),
        WorkflowEdge("loop-confidence", "observations", "contract-test-node", "confidence_observations"),
    )
    return ModulePackageContractCase(
        case_id="evaluate-inserted-loop",
        node_type_id="structure_comparison.evaluate_inserted_loop",
        node_type_version="2.0.0",
        binding_id="structure_comparison.evaluate_inserted_loop.direct",
        binding_version="2.0.0",
        node_parameters={
            "resolved_core_residue_ids": ["A:1", "A:2", "A:3", "A:4"],
            "loop_residue_ids": ["A:loop"],
            "left_junction_residue_id": "A:2",
            "right_junction_residue_id": "A:3",
            "resolved_core_tm_score_minimum": 0.75,
            "resolved_core_rmsd_angstrom_maximum": 3.0,
            "counterpart_tm_score_minimum": 0.70,
            "counterpart_rmsd_angstrom_maximum": 3.5,
            "resolved_core_mean_plddt_minimum": 70.0,
            "junction_cn_distance_angstrom_minimum": 1.15,
            "junction_cn_distance_angstrom_maximum": 1.55,
            "loop_core_nonbonded_distance_angstrom_minimum": 2.0,
        },
        binding_parameters={},
        environment_values={},
        workflow_nodes=(
            source,
            subject_axis,
            reference_axis,
            counterpart_axis,
            core_alignment,
            core_tm,
            core_rmsd,
            counterpart_alignment,
            counterpart_tm,
            counterpart_rmsd,
            prediction_axis,
            confidence_facts,
            confidence,
        ),
        workflow_edges=edges,
        expected_candidate_counts={"passing_candidates": 1},
    )


def _run_inserted_loop_failure_case(
    case: ModulePackageContractCase,
    tmp_path: Path,
) -> RunProjection:
    support = (
        TRANSFORM_PACKAGE,
        SOURCE_PACKAGE,
        COLLECTION_OPS_PACKAGE,
        STRUCTURE_PREDICTION_PACKAGE,
    )
    catalog = build_frozen_catalog((MODULE_PACKAGE, *support))
    manager = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = manager.create(case.case_id)
    authoring = WorkflowAuthoringService(manager, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            *case.workflow_nodes,
            WorkflowNodeInstance(
                node_id="contract-test-node",
                node_type_id=case.node_type_id,
                node_type_version=case.node_type_version,
                binding_id=case.binding_id,
                binding_version=case.binding_version,
                node_parameters=case.node_parameters,
                binding_parameters=case.binding_parameters,
            ),
        ),
        edges=case.workflow_edges,
        contract_lock=(),
        observation_selectors=(),
        selection_objectives=(),
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    service = V2RunService(
        manager,
        catalog,
        authoring,
        admit_environment_configuration(catalog, {}),
        result_store(manager),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=case.case_id,
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    return projection


def _assert_inserted_loop_failure(projection: RunProjection) -> None:
    assert projection.status == "failed"
    assert next(
        disposition
        for disposition in projection.node_dispositions
        if disposition.node_id == "contract-test-node"
    ).outcome == "failed"
    assert not any(
        output.node_id == "contract-test-node"
        for output in projection.outputs
    )


def test_inserted_loop_rejects_lawful_missing_loop_scoped_plddt(
    tmp_path: Path,
) -> None:
    projection = _run_inserted_loop_failure_case(
        _inserted_loop_ctk_case(missing_loop_plddt=True),
        tmp_path,
    )
    _assert_inserted_loop_failure(projection)


def test_inserted_loop_rejects_the_wrong_confidence_metric(
    tmp_path: Path,
) -> None:
    projection = _run_inserted_loop_failure_case(
        _inserted_loop_ctk_case(
            confidence_binding_id=(
                "contract_test.esmfold2_confidence_source.fixture"
            )
        ),
        tmp_path,
    )
    _assert_inserted_loop_failure(projection)


def _three_way_ctk_case() -> ModulePackageContractCase:
    source = _three_way_node(
        "source",
        "contract_test.1pga_three_way_source",
        "5.0.0",
        "contract_test.1pga_three_way_source.fixture",
        "5.0.0",
    )
    nodes = (
        source,
        *(
            _three_way_node(
                f"axis-{role}",
                "structure_transform.resolve_candidate_residue_axes",
                "6.0.0",
                "structure_transform.resolve_candidate_residue_axes.direct",
                "6.0.0",
            )
            for role in ("input", "esmfold2", "simplefold")
        ),
        _three_way_node(
            "pair-methods",
            "collection_ops.pair_siblings_by_parent",
            "4.0.0",
            "collection_ops.pair_siblings_by_parent.direct",
            "4.0.0",
        ),
        _three_way_node(
            "prediction-axis",
            "contract_test.prediction_axis_source",
            "5.0.0",
            "contract_test.prediction_axis_source.fixture",
            "5.0.0",
        ),
        _three_way_node(
            "align-esmfold2-input",
            "structure_comparison.align_fixed_reference",
            "5.0.0",
            "structure_comparison.align_fixed_reference.sequence_primary_affine",
            "5.0.0",
        ),
        _three_way_node(
            "align-simplefold-input",
            "structure_comparison.align_fixed_reference",
            "5.0.0",
            "structure_comparison.align_fixed_reference.sequence_primary_affine",
            "5.0.0",
        ),
        _three_way_node(
            "align-methods",
            "structure_comparison.align_counterparts",
            "5.0.0",
            "structure_comparison.align_counterparts.sequence_primary_affine",
            "5.0.0",
        ),
        *(
            _three_way_node(
                f"{metric}-{edge}",
                f"structure_comparison.{metric}_{mode}",
                "6.0.0",
                (
                    f"structure_comparison.{metric}_{mode}."
                    "from_alignment_evidence"
                ),
                "6.0.0",
            )
            for edge, mode in (
                ("esmfold2-input", "fixed_reference"),
                ("simplefold-input", "fixed_reference"),
                ("methods", "counterparts"),
            )
            for metric in ("tm_score", "rmsd")
        ),
        _three_way_node(
            "confidence-esmfold2",
            "contract_test.prediction_confidence_source",
            "5.0.0",
            "contract_test.esmfold2_confidence_source.fixture",
            "5.0.0",
        ),
        _three_way_node(
            "confidence-fact-esmfold2",
            "contract_test.prediction_confidence_fact_source",
            "5.0.0",
            "contract_test.esmfold2_confidence_fact_source.fixture",
            "5.0.0",
        ),
        _three_way_node(
            "confidence-simplefold",
            "contract_test.prediction_confidence_source",
            "5.0.0",
            "contract_test.simplefold_confidence_source.fixture",
            "5.0.0",
        ),
        _three_way_node(
            "confidence-fact-simplefold",
            "contract_test.prediction_confidence_fact_source",
            "5.0.0",
            "contract_test.simplefold_confidence_fact_source.fixture",
            "5.0.0",
        ),
    )
    edges: list[WorkflowEdge] = []
    for role, source_port in (
        ("input", "input_structures"),
        ("esmfold2", "esmfold2_structures"),
        ("simplefold", "simplefold_structures"),
    ):
        edges.append(
            WorkflowEdge(source.node_id, source_port, f"axis-{role}", "structure_candidates")
        )
    edges.extend(
        (
            WorkflowEdge("source", "esmfold2_structures", "pair-methods", "subjects"),
            WorkflowEdge("source", "simplefold_structures", "pair-methods", "references"),
            WorkflowEdge(
                "source",
                "sequence_parents",
                "prediction-axis",
                "sequence_parents",
            ),
        )
    )
    for edge_id, subject_role, reference_role, alignment_node in (
        ("esmfold2-input", "esmfold2", "input", "align-esmfold2-input"),
        ("simplefold-input", "simplefold", "input", "align-simplefold-input"),
        ("methods", "esmfold2", "simplefold", "align-methods"),
    ):
        edges.extend(
            (
                WorkflowEdge("source", f"{subject_role}_structures", alignment_node, "subjects"),
                WorkflowEdge(f"axis-{subject_role}", "residue_axes", alignment_node, "subject_residue_axes"),
                WorkflowEdge("source", f"{reference_role}_structures", alignment_node, "references"),
                WorkflowEdge(f"axis-{reference_role}", "residue_axes", alignment_node, "reference_residue_axes"),
            )
        )
        if edge_id == "methods":
            edges.append(WorkflowEdge("pair-methods", "pairing", alignment_node, "pairing"))
        for metric in ("tm_score", "rmsd"):
            score_node = f"{metric}-{edge_id}"
            edges.extend(
                (
                    WorkflowEdge(alignment_node, "alignments", score_node, "alignments"),
                    WorkflowEdge("source", f"{subject_role}_structures", score_node, "subjects"),
                    WorkflowEdge("source", f"{reference_role}_structures", score_node, "references"),
                )
            )
            if edge_id == "methods":
                edges.append(WorkflowEdge("pair-methods", "pairing", score_node, "pairing"))
    for role in ("esmfold2", "simplefold"):
        edges.extend(
            (
                WorkflowEdge(
                    "prediction-axis",
                    "prediction_axis",
                    f"confidence-fact-{role}",
                    "prediction_axis",
                ),
                WorkflowEdge(
                    "source",
                    f"{role}_structures",
                    f"confidence-fact-{role}",
                    "structures",
                ),
                WorkflowEdge(
                    f"confidence-fact-{role}",
                    "confidence_facts",
                    f"confidence-{role}",
                    "confidence_facts",
                ),
                WorkflowEdge("source", f"{role}_structures", f"confidence-{role}", "structures"),
            )
        )
    target_ports = {
        "input_structures": ("source", "input_structures"),
        "sequence_parents": ("source", "sequence_parents"),
        "esmfold2_structures": ("source", "esmfold2_structures"),
        "simplefold_structures": ("source", "simplefold_structures"),
        "input_residue_axes": ("axis-input", "residue_axes"),
        "esmfold2_residue_axes": ("axis-esmfold2", "residue_axes"),
        "simplefold_residue_axes": ("axis-simplefold", "residue_axes"),
        "method_pairing": ("pair-methods", "pairing"),
        "input_esmfold2_alignments": ("align-esmfold2-input", "alignments"),
        "input_simplefold_alignments": ("align-simplefold-input", "alignments"),
        "method_alignments": ("align-methods", "alignments"),
        "input_esmfold2_tm_scores": ("tm_score-esmfold2-input", "scores"),
        "input_esmfold2_rmsd_scores": ("rmsd-esmfold2-input", "scores"),
        "input_simplefold_tm_scores": ("tm_score-simplefold-input", "scores"),
        "input_simplefold_rmsd_scores": ("rmsd-simplefold-input", "scores"),
        "method_tm_scores": ("tm_score-methods", "scores"),
        "method_rmsd_scores": ("rmsd-methods", "scores"),
        "esmfold2_confidence": ("confidence-esmfold2", "observations"),
        "simplefold_confidence": ("confidence-simplefold", "observations"),
    }
    edges.extend(
        WorkflowEdge(source_node, source_port, "contract-test-node", target_port)
        for target_port, (source_node, source_port) in target_ports.items()
    )
    return ModulePackageContractCase(
        case_id="classify-1pga-three-way-consistency",
        node_type_id="structure_comparison.classify_three_way_consistency",
        node_type_version="3.0.0",
        binding_id="structure_comparison.classify_three_way_consistency.direct",
        binding_version="3.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=nodes,
        workflow_edges=tuple(edges),
    )


def _three_way_consistency_value() -> ThreeWayConsistencyEvidence:
    input_reference = CandidateDataReference(
        "input", "protein.structure", "sha256:" + "5" * 64
    )
    sequence_reference = CandidateDataReference(
        "sequence", "protein.sequence", "sha256:" + "6" * 64
    )
    esmfold2_reference = CandidateDataReference(
        "esmfold2", "protein.structure", "sha256:" + "7" * 64
    )
    simplefold_reference = CandidateDataReference(
        "simplefold", "protein.structure", "sha256:" + "8" * 64
    )
    confidences = (
        ThreeWayConfidenceEvidence(
            "esmfold2",
            esmfold2_reference,
            REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
            90.0,
            True,
            "sha256:" + "9" * 64,
        ),
        ThreeWayConfidenceEvidence(
            "simplefold",
            simplefold_reference,
            SIMPLEFOLD_FOLD_METHOD_REFERENCE,
            90.0,
            True,
            "sha256:" + "a" * 64,
        ),
    )
    edge_specs = (
        ("input_esmfold2", esmfold2_reference, input_reference, "b", "c", "d"),
        ("input_simplefold", simplefold_reference, input_reference, "e", "f", "0"),
        (
            "esmfold2_simplefold",
            esmfold2_reference,
            simplefold_reference,
            "1",
            "2",
            "3",
        ),
    )
    edges = tuple(
        ThreeWayComparisonEdge(
            edge_id=edge_id,
            subject=subject,
            reference=reference_candidate,
            alignment_evidence_content_digest="sha256:" + digest * 64,
            alignment_method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
            normalization_length=75,
            aligned_atom_count=75,
            tm_score=1.0,
            rmsd_angstrom=0.0,
            tm_score_method=TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
            rmsd_method=RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
            tm_score_content_digest="sha256:" + tm_digest * 64,
            rmsd_content_digest="sha256:" + rmsd_digest * 64,
            close=True,
        )
        for edge_id, subject, reference_candidate, digest, tm_digest, rmsd_digest in edge_specs
    )
    return ThreeWayConsistencyEvidence(
        input_structure=input_reference,
        sequence_parent=sequence_reference,
        esmfold2_structure=esmfold2_reference,
        simplefold_structure=simplefold_reference,
        classification_method=THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
        input_b_factor_semantics="uninterpreted_coordinate_temperature_factor",
        residue_count=75,
        plddt_threshold=70.0,
        tm_score_threshold=0.8,
        rmsd_threshold_angstrom=2.5,
        confidences=confidences,
        edges=edges,
        classification="three_way_consistent",
        subreason=None,
    )


def test_three_way_thresholds_are_inclusive_and_exact() -> None:
    value = _three_way_consistency_value()
    exact_confidence = replace(
        value.confidences[0],
        mean_residue_plddt=70.0,
        eligible=True,
    )
    exact_edge = replace(
        value.edges[0],
        tm_score=0.8,
        rmsd_angstrom=2.5,
        close=True,
    )
    validate_three_way_consistency(
        replace(
            value,
            confidences=(exact_confidence, value.confidences[1]),
            edges=(exact_edge, *value.edges[1:]),
        )
    )

    below_confidence = replace(
        exact_confidence,
        mean_residue_plddt=69.999999,
        eligible=False,
    )
    validate_three_way_consistency(
        replace(
            value,
            confidences=(below_confidence, value.confidences[1]),
            classification="insufficient_evidence",
            subreason="method_confidence_below_threshold",
        )
    )
    for outside_edge in (
        replace(exact_edge, tm_score=0.799999, close=False),
        replace(exact_edge, rmsd_angstrom=2.500001, close=False),
    ):
        validate_three_way_consistency(
            replace(
                value,
                edges=(outside_edge, *value.edges[1:]),
                classification="insufficient_evidence",
                subreason="threshold_boundary_nontransitive",
            )
        )


def test_three_way_port_requires_tuples_and_exact_method_references() -> None:
    value = _three_way_consistency_value()
    with pytest.raises(ValueError, match="exact tuple"):
        validate_three_way_consistency(
            replace(value, confidences=list(value.confidences))
        )
    with pytest.raises(ValueError, match="exact tuple"):
        validate_three_way_consistency(replace(value, edges=list(value.edges)))
    wrong_digest = replace(
        value.confidences[0].method,
        contract_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(ValueError, match="confidence evidence"):
        validate_three_way_consistency(
            replace(
                value,
                confidences=(
                    replace(value.confidences[0], method=wrong_digest),
                    value.confidences[1],
                ),
            )
        )
    wrong_kind = replace(value.classification_method, contract_kind="metric")
    with pytest.raises(ValueError, match="not canonical"):
        validate_three_way_consistency(
            replace(value, classification_method=wrong_kind)
        )


def test_package_ports_project_all_nested_candidate_data_references() -> None:
    three_way = _three_way_consistency_value()
    assert {
        reference.candidate_id
        for reference in THREE_WAY_CONSISTENCY_PORT_TYPE.candidate_data_references(
            three_way,
            {},
        )
    } == {"input", "sequence", "esmfold2", "simplefold"}

    inserted_loop = _inserted_loop_port_case().valid_value
    assert {
        reference.candidate_id
        for reference in INSERTED_LOOP_EVALUATION_PORT_TYPE.candidate_data_references(
            inserted_loop,
            {},
        )
    } == {"loop-subject", "loop-reference", "loop-counterpart"}


def _inserted_loop_port_case() -> ModulePackagePortCase:
    left_junction = AtomPairDistanceEvidence(
        "A:2",
        "A:2",
        "C",
        (0.0, 0.0, 0.0),
        "A:loop",
        "A:3",
        "N",
        (1.35, 0.0, 0.0),
        1.35,
    )
    right_junction = AtomPairDistanceEvidence(
        "A:loop",
        "A:3",
        "C",
        (0.0, 0.0, 0.0),
        "A:3",
        "A:4",
        "N",
        (1.35, 0.0, 0.0),
        1.35,
    )
    minimum_distance = AtomPairDistanceEvidence(
        "A:loop",
        "A:3",
        "CA",
        (0.0, 0.0, 0.0),
        "A:1",
        "A:1",
        "CA",
        (2.0, 0.0, 0.0),
        2.0,
    )
    loop_evidence = InsertedLoopEvaluationCollection(
        (
            InsertedLoopCandidateEvidence(
                subject=CandidateDataReference(
                    "loop-subject",
                    "protein.structure",
                    "sha256:" + "4" * 64,
                ),
                reference=CandidateDataReference(
                    "loop-reference",
                    "protein.structure",
                    "sha256:" + "5" * 64,
                ),
                counterpart=CandidateDataReference(
                    "loop-counterpart",
                    "protein.structure",
                    "sha256:" + "6" * 64,
                ),
                prediction_axis_content_digest="sha256:" + "7" * 64,
                structure_axis_content_digest="sha256:" + "8" * 64,
                prediction_to_structure_correspondence=(
                    ResidueIdentityCorrespondence("A:1", "A:1"),
                    ResidueIdentityCorrespondence("A:2", "A:2"),
                    ResidueIdentityCorrespondence("A:loop", "A:3"),
                    ResidueIdentityCorrespondence("A:3", "A:4"),
                    ResidueIdentityCorrespondence("A:4", "A:5"),
                ),
                resolved_core_residue_ids=("A:1", "A:2", "A:3", "A:4"),
                loop_residue_ids=("A:loop",),
                resolved_core_alignment_content_digest="sha256:" + "9" * 64,
                counterpart_alignment_content_digest="sha256:" + "a" * 64,
                resolved_core_tm_score=1.0,
                resolved_core_rmsd_angstrom=0.0,
                counterpart_tm_score=1.0,
                counterpart_rmsd_angstrom=0.0,
                confidence_collection_content_digest="sha256:" + "b" * 64,
                confidence_method=REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
                resolved_core_mean_plddt=90.0,
                loop_mean_plddt=80.0,
                left_junction=left_junction,
                right_junction=right_junction,
                minimum_loop_core_nonbonded_distance=minimum_distance,
                thresholds=InsertedLoopThresholds(
                    0.75, 3.0, 0.70, 3.5, 70.0, 1.15, 1.55, 2.0
                ),
                resolved_core_passed=True,
                counterpart_passed=True,
                confidence_passed=True,
                junctions_passed=True,
                clash_passed=True,
                accepted=True,
                method=INSERTED_LOOP_EVALUATION_METHOD_REFERENCE,
            ),
        )
    )
    return ModulePackagePortCase(
        "structure_comparison.inserted_loop_evaluation",
        "2.0.0",
        loop_evidence,
        (
            object(),
            replace(
                loop_evidence,
                entries=(replace(loop_evidence.entries[0], accepted=False),),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        left_junction=replace(
                            left_junction,
                            left_structure_residue_id="A:4",
                        ),
                    ),
                ),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        left_junction=AtomPairDistanceEvidence(
                            "A:1",
                            "A:1",
                            "C",
                            (0.0, 0.0, 0.0),
                            "A:loop",
                            "A:3",
                            "N",
                            (1.35, 0.0, 0.0),
                            1.35,
                        ),
                    ),
                ),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        minimum_loop_core_nonbonded_distance=replace(
                            minimum_distance,
                            left_atom_name="H",
                            right_atom_name="H",
                        ),
                    ),
                ),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        confidence_method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
                    ),
                ),
            ),
        ),
    )


def test_structure_comparison_contract_test_kit(
    tmp_path: Path,
) -> None:
    axis = _axis("S", "AA", ((1.0, 0.0, 0.0), (2.0, 0.0, 0.0)))
    reference_axis = _axis(
        "R",
        "AA",
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    )
    resolved = align_resolved_axes(axis, reference_axis)
    evidence = StructureAlignmentEvidence(
        subject=CandidateDataReference(
            candidate_id="subject",
            data_type_id="protein.structure",
            content_digest="sha256:" + "1" * 64,
        ),
        reference=CandidateDataReference(
            candidate_id="reference",
            data_type_id="protein.structure",
            content_digest="sha256:" + "2" * 64,
        ),
        subject_axis_content_digest="sha256:" + "3" * 64,
        reference_axis_content_digest="sha256:" + "4" * 64,
        segment_map=resolved.segment_map,
        policy=resolved.policy,
        correspondence=resolved.correspondence,
        transform=resolved.transform,
        normalization=resolved.normalization,
        rmsd=resolved.rmsd,
        coverage=resolved.coverage,
        method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    )
    cases = (
        _ctk_case(
            case_id="align-single-sequence",
            operation="align_single",
            binding_id=(
                "structure_comparison.align_single.sequence_primary_affine"
            ),
            pairing_mode=None,
        ),
        _ctk_case(
            case_id="align-single-tm",
            operation="align_single",
            binding_id=(
                "structure_comparison.align_single.structure_first_tm_align"
            ),
            pairing_mode=None,
        ),
        _ctk_case(
            case_id="align-pairwise-fixed",
            operation="align_pairwise",
            binding_id=(
                "structure_comparison.align_fixed_reference."
                "sequence_primary_affine"
            ),
            pairing_mode="fixed_reference",
        ),
        _ctk_case(
            case_id="align-pairwise-counterpart",
            operation="align_pairwise",
            binding_id=(
                "structure_comparison.align_counterparts."
                "sequence_primary_affine"
            ),
            pairing_mode="per_subject_counterpart",
        ),
        *tuple(
            _ctk_case(
                case_id=f"{operation}-{pairing_mode}",
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

    support = (
        TRANSFORM_PACKAGE,
        SOURCE_PACKAGE,
        COLLECTION_OPS_PACKAGE,
        STRUCTURE_PREDICTION_PACKAGE,
    )
    catalog = build_frozen_catalog((MODULE_PACKAGE, *support))

    def reference(
        kind: str,
        contract_id: str,
        version: str,
    ) -> ExactContractReference:
        return ExactContractReference(
            **catalog.require_contract(kind, contract_id, version).reference()
        )

    input_reference = CandidateDataReference(
        "input", "protein.structure", "sha256:" + "5" * 64
    )
    sequence_reference = CandidateDataReference(
        "sequence", "protein.sequence", "sha256:" + "6" * 64
    )
    esmfold2_reference = CandidateDataReference(
        "esmfold2", "protein.structure", "sha256:" + "7" * 64
    )
    simplefold_reference = CandidateDataReference(
        "simplefold", "protein.structure", "sha256:" + "8" * 64
    )
    confidences = (
        ThreeWayConfidenceEvidence(
            "esmfold2",
            esmfold2_reference,
            reference(
                "method",
                "folding.fold.esmfold2_fast_biohub_2026_05",
                "4.0.0",
            ),
            90.0,
            True,
            "sha256:" + "9" * 64,
        ),
        ThreeWayConfidenceEvidence(
            "simplefold",
            simplefold_reference,
            reference(
                "method",
                "folding.fold.simplefold_100m_c7a5570",
                "5.0.0",
            ),
            90.0,
            True,
            "sha256:" + "a" * 64,
        ),
    )
    edges = tuple(
        ThreeWayComparisonEdge(
            edge_id=edge_id,
            subject=subject,
            reference=reference_candidate,
            alignment_evidence_content_digest="sha256:" + digest * 64,
            alignment_method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
            normalization_length=75,
            aligned_atom_count=75,
            tm_score=1.0,
            rmsd_angstrom=0.0,
            tm_score_method=TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
            rmsd_method=RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
            tm_score_content_digest="sha256:" + tm_digest * 64,
            rmsd_content_digest="sha256:" + rmsd_digest * 64,
            close=True,
        )
        for edge_id, subject, reference_candidate, digest, tm_digest, rmsd_digest in (
            (
                "input_esmfold2",
                esmfold2_reference,
                input_reference,
                "b",
                "c",
                "d",
            ),
            (
                "input_simplefold",
                simplefold_reference,
                input_reference,
                "e",
                "f",
                "0",
            ),
            (
                "esmfold2_simplefold",
                esmfold2_reference,
                simplefold_reference,
                "1",
                "2",
                "3",
            ),
        )
    )
    consistency = ThreeWayConsistencyEvidence(
        input_structure=input_reference,
        sequence_parent=sequence_reference,
        esmfold2_structure=esmfold2_reference,
        simplefold_structure=simplefold_reference,
        classification_method=reference(
            "method",
            "structure_comparison.three_way_consistency.threshold_graph",
            "2.0.0",
        ),
        input_b_factor_semantics="uninterpreted_coordinate_temperature_factor",
        residue_count=75,
        plddt_threshold=70.0,
        tm_score_threshold=0.8,
        rmsd_threshold_angstrom=2.5,
        confidences=confidences,
        edges=edges,
        classification="three_way_consistent",
        subreason=None,
    )
    inserted_loop_port_case = _inserted_loop_port_case()

    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=cases,
        port_cases=(
                ModulePackagePortCase(
                    "structure_comparison.alignment_evidence",
                    "5.0.0",
                evidence,
                (object(), replace(evidence, correspondence=())),
            ),
                ModulePackagePortCase(
                    "structure_comparison.three_way_consistency",
                "3.0.0",
                consistency,
                (object(), replace(consistency, classification="all_disagree")),
                ),
                inserted_loop_port_case,
        ),
        supporting_registrations=support,
        work_root=tmp_path,
    )

    assert len(report.case_reports) == 10
    assert {case.status for case in report.case_reports} == {"succeeded"}
