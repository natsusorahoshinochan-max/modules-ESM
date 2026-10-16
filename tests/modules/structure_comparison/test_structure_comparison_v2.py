"""Focused v3 contracts for resolved-axis structure alignment."""

from __future__ import annotations

from tests.scenarios.structure_comparison import (
    _alignment_edges,
    _axis_edges,
    _axis_node,
    _ctk_case,
    _inserted_loop_ctk_case,
    _inserted_loop_port_case,
    _source_node,
    _three_way_consistency_value,
    _three_way_ctk_case,
    _three_way_node,
)

from core.catalog.authoring import AuthoringCapabilityProjection

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
from core.catalog.errors import PortValueError
from core.execution.environment import admit_environment_configuration
from core.execution.ledger.projections import RunProjection
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackagePortCase,
    execute_module_package_case,
    verify_module_package_port,
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
from datatypes.observation import (
    CandidateRelation,
    CandidateRelationEntry,
    ScoreCollection,
    ScoreObservation,
)
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
    LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE,
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
    from modules.structure_comparison.three_way import (
        _singleton_axis as _three_way_axis,
    )
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
            contract_id=RESOLVED_AXIS_PORT_TYPE.type_id),
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

    assert _three_way_axis(call, "axes") == (
        subject,
        residue_axis,
        admitted_axis,
    )


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
    decoded = ALIGNMENT_EVIDENCE_PORT_TYPE.decode(
        ALIGNMENT_EVIDENCE_PORT_TYPE.encode(evidence)
    )
    assert type(decoded.rmsd) is float
    assert type(decoded.coverage) is float
    assert all(
        type(number) is float
        for correspondence in decoded.correspondence
        for number in (
            *correspondence.subject_coordinate,
            *correspondence.reference_coordinate,
            *correspondence.transformed_subject_coordinate,
            correspondence.residual_distance,
        )
    )
    assert all(
        type(number) is float
        for row in decoded.transform.row_vector_rotation
        for number in row
    )
    assert all(
        type(number) is float for number in decoded.transform.translation
    )

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
        ALIGNMENT_EVIDENCE_PORT_TYPE.validate(impossible)


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
        "protein.structure")
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
    relation = CandidateRelation((CandidateRelationEntry(
        subject_reference,
        reference_reference,
    ),))
    resources = _CountingRunResources()
    binding_id = "structure_comparison.align_pairs.sequence_primary_affine"
    build_operation(
        catalog,
        binding_id,
        resources)
    with pytest.raises(ValueError, match="structure content digest"):
        operation_call(
            catalog=catalog,
            binding_id=binding_id,
            inputs={
                "subject_residue_axes": subject_axes,
                "reference_residue_axes": reference_axes,
                "relation": relation,
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
    relation = CandidateRelation((
        CandidateRelationEntry(alpha_reference, fixed_reference),
        CandidateRelationEntry(zeta_reference, fixed_reference),
    ))
    alignment_binding = (
        "structure_comparison.align_pairs.sequence_primary_affine"
    )
    aligner = build_operation(
        catalog,
        alignment_binding,
        _RunResources())
    call = operation_call(
        catalog=catalog,
        binding_id=alignment_binding,
        inputs={
            "subject_residue_axes": subject_axes,
            "reference_residue_axes": reference_axes,
            "relation": relation,
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
        "structure_comparison.tm_score_from_alignments."
        "from_alignment_evidence"
    )
    scorer = build_operation(
        catalog,
        metric_binding,
        _RunResources())
    observed = scorer.execute(
        operation_call(
            catalog=catalog,
            binding_id=metric_binding,
            inputs={
                "alignments": aligned,
                "subjects": subjects,
                "references": references,
                "relation": relation,
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
        metric_binding)
    metric_inputs = {
        "alignments": aligned,
        "subjects": subjects,
        "references": references,
        "relation": relation,
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


def test_direct_ancestor_tm_score_allows_one_reference_for_two_subjects() -> None:
    catalog = build_frozen_catalog((TRANSFORM_PACKAGE, MODULE_PACKAGE))
    reference_structure = _multi_segment_structure(
        (("R", "AA", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))),)
    )
    subject_structures = tuple(
        _multi_segment_structure(
            ((name, "AA", ((offset, 0.0, 0.0), (offset + 1, 0.0, 0.0))),)
        )
        for name, offset in (("A", 2.0), ("B", 4.0))
    )
    subject_references = tuple(
        _candidate_reference(f"subject-{index}", structure)
        for index, structure in enumerate(subject_structures)
    )
    ancestor_reference = _candidate_reference("ancestor", reference_structure)
    subjects = CandidateCollection(
        "subjects",
        "protein.structure",
        tuple(
            Candidate(f"subject-{index}", structure)
            for index, structure in enumerate(subject_structures)
        ),
    )
    ancestors = CandidateCollection(
        "ancestors",
        "protein.structure",
        (Candidate("ancestor", reference_structure),),
    )
    pairing = CandidateRelation(tuple(
        CandidateRelationEntry(reference, ancestor_reference)
        for reference in subject_references
    ))
    subject_axes = CandidateResolvedResidueAxisAssociations(tuple(
        CandidateResolvedResidueAxisAssociation(
            reference,
            resolve_residue_axis(structure),
        )
        for reference, structure in zip(
            subject_references,
            subject_structures,
            strict=True,
        )
    ))
    ancestor_axes = CandidateResolvedResidueAxisAssociations((
        CandidateResolvedResidueAxisAssociation(
            ancestor_reference,
            resolve_residue_axis(reference_structure),
        ),
    ))
    alignment_binding = (
        "structure_comparison.align_pairs."
        "sequence_primary_affine"
    )
    alignments = build_operation(
        catalog,
        alignment_binding,
        _RunResources(),
    ).execute(operation_call(
        catalog=catalog,
        binding_id=alignment_binding,
        inputs={
            "subject_residue_axes": subject_axes,
            "reference_residue_axes": ancestor_axes,
            "relation": pairing,
        },
        node_parameters={"pin_matching_chain_ids": False},
    ))["alignments"]
    metric_binding = (
        "structure_comparison.tm_score_from_alignments."
        "from_alignment_evidence"
    )
    scores = build_operation(
        catalog,
        metric_binding,
        _RunResources(),
    ).execute(operation_call(
        catalog=catalog,
        binding_id=metric_binding,
        inputs={
            "alignments": alignments,
            "subjects": subjects,
            "references": ancestors,
            "relation": pairing,
        },
    ))["scores"]

    assert len(alignments) == 2
    assert {entry.reference for entry in alignments} == {ancestor_reference}
    assert [entry.subject for entry in scores.entries] == list(
        subject_references
    )
    assert all(
        entry.context.pairing_mode == "explicit_relation"
        and entry.context.reference.candidate == ancestor_reference
        for entry in scores.entries
    )


def test_structure_comparison_catalog_has_the_split_scientific_paths() -> None:
    catalog = build_frozen_catalog((TRANSFORM_PACKAGE, MODULE_PACKAGE))
    contracts = [
        contract
        for contract in catalog.contracts
        if contract.contract_id.startswith("structure_comparison.")
    ]

    assert contracts
    assert {
        contract.contract_id
        for contract in contracts
        if contract.contract_kind == "node_type"
    } == {
        "structure_comparison.align_pairs",
        "structure_comparison.evaluate_inserted_loop",
        "structure_comparison.classify_three_way_consistency",
        "structure_comparison.rmsd_from_alignments",
        "structure_comparison.tm_score_from_alignments",
    }
    for name in (
        "align_pairs",
        "rmsd_from_alignments",
        "tm_score_from_alignments",
    ):
        node = catalog.require_contract(
            "node_type", f"structure_comparison.{name}"
        )
        relation = {
            item["name"]: item for item in node.descriptor["inputs"]
        }["relation"]
        assert relation["required"] is True
        assert relation["port_type"]["contract_id"] == "candidate.relation"
        if name != "align_pairs":
            scores = next(
                item
                for item in node.descriptor["outputs"]
                if item["name"] == "scores"
            )
            assert scores["port_type"]["contract_id"] == "score.collection"
    score_bindings = [
        contract
        for contract in contracts
        if contract.contract_kind == "binding"
        and (
            ".rmsd_from_alignments." in contract.contract_id
            or ".tm_score_from_alignments." in contract.contract_id
        )
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
                binding_id=case.binding_id,
                node_parameters=case.node_parameters,
                binding_parameters=case.binding_parameters,
            ),
        ),
        edges=case.workflow_edges,
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
        NodeAttemptFactory(
            manager,
            admit_environment_configuration(catalog, {}),
            result_store(manager),
        ),
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
        publication.node_id == "contract-test-node"
        for publication in projection.publications
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


def test_three_way_codec_preserves_declared_float_values() -> None:
    value = _three_way_consistency_value()
    decoded = THREE_WAY_CONSISTENCY_PORT_TYPE.decode(
        THREE_WAY_CONSISTENCY_PORT_TYPE.encode(value)
    )

    assert all(
        type(number) is float
        for number in (
            decoded.plddt_threshold,
            decoded.tm_score_threshold,
            decoded.rmsd_threshold_angstrom,
            *(item.mean_residue_plddt for item in decoded.confidences),
            *(item.tm_score for item in decoded.edges),
            *(item.rmsd_angstrom for item in decoded.edges),
        )
    )


def test_three_way_port_requires_tuples_and_stable_method_references() -> None:
    value = _three_way_consistency_value()
    with pytest.raises(ValueError, match="exact tuple"):
        validate_three_way_consistency(
            replace(value, confidences=list(value.confidences))
        )
    with pytest.raises(ValueError, match="exact tuple"):
        validate_three_way_consistency(replace(value, edges=list(value.edges)))
    with pytest.raises(ValueError, match="confidence evidence"):
        validate_three_way_consistency(
            replace(
                value,
                confidences=(
                    value.confidences[0],
                    replace(
                        value.confidences[1],
                        method=LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE,
                    ),
                ),
            )
        )
    wrong_kind = replace(value.classification_method, contract_kind="metric")
    with pytest.raises(ValueError, match="not canonical"):
        validate_three_way_consistency(
            replace(value, classification_method=wrong_kind)
        )


def test_three_way_port_accepts_exact_local_esmfold2_method() -> None:
    value = _three_way_consistency_value()
    local_value = replace(
        value,
        confidences=(
            replace(
                value.confidences[0],
                method=LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE,
            ),
            value.confidences[1],
        ),
    )

    decoded = THREE_WAY_CONSISTENCY_PORT_TYPE.decode(
        THREE_WAY_CONSISTENCY_PORT_TYPE.encode(local_value)
    )

    assert (
        decoded.confidences[0].method
        == LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE
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




def test_inserted_loop_codec_preserves_declared_float_values() -> None:
    value = _inserted_loop_port_case().valid_value
    decoded = INSERTED_LOOP_EVALUATION_PORT_TYPE.decode(
        INSERTED_LOOP_EVALUATION_PORT_TYPE.encode(value)
    )
    entry = decoded.entries[0]

    assert all(
        type(number) is float
        for number in (
            entry.resolved_core_tm_score,
            entry.resolved_core_rmsd_angstrom,
            entry.counterpart_tm_score,
            entry.counterpart_rmsd_angstrom,
            entry.resolved_core_mean_plddt,
            entry.loop_mean_plddt,
            entry.thresholds.resolved_core_tm_score_minimum,
            entry.thresholds.resolved_core_rmsd_angstrom_maximum,
            entry.thresholds.counterpart_tm_score_minimum,
            entry.thresholds.counterpart_rmsd_angstrom_maximum,
            entry.thresholds.resolved_core_mean_plddt_minimum,
            entry.thresholds.junction_cn_distance_angstrom_minimum,
            entry.thresholds.junction_cn_distance_angstrom_maximum,
            entry.thresholds.loop_core_nonbonded_distance_angstrom_minimum,
        )
    )
    assert all(
        type(number) is float
        for atom_pair in (
            entry.left_junction,
            entry.right_junction,
            entry.minimum_loop_core_nonbonded_distance,
        )
        for number in (
            *atom_pair.left_coordinate,
            *atom_pair.right_coordinate,
            atom_pair.distance_angstrom,
        )
    )


def test_inserted_loop_port_accepts_exact_local_esmfold2_method() -> None:
    value = _inserted_loop_port_case().valid_value
    local_value = replace(
        value,
        entries=(
            replace(
                value.entries[0],
                confidence_method=LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE,
            ),
        ),
    )

    decoded = INSERTED_LOOP_EVALUATION_PORT_TYPE.decode(
        INSERTED_LOOP_EVALUATION_PORT_TYPE.encode(local_value)
    )

    assert (
        decoded.entries[0].confidence_method
        == LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE
    )


@pytest.mark.parametrize(
    "case",
    (
        _ctk_case(
            case_id="align-pairs-sequence",
            operation="align_pairs",
            binding_id="structure_comparison.align_pairs.sequence_primary_affine",
            pairing_mode="explicit_relation",
        ),
        _ctk_case(
            case_id="align-pairs-tm",
            operation="align_pairs",
            binding_id="structure_comparison.align_pairs.structure_first_tm_align",
            pairing_mode="explicit_relation",
        ),
        _ctk_case(
            case_id="rmsd-from-alignments",
            operation="rmsd",
            binding_id="structure_comparison.rmsd_from_alignments.from_alignment_evidence",
            pairing_mode="explicit_relation",
        ),
        _ctk_case(
            case_id="tm-score-from-alignments",
            operation="tm_score",
            binding_id="structure_comparison.tm_score_from_alignments.from_alignment_evidence",
            pairing_mode="explicit_relation",
        ),
        _three_way_ctk_case(),
        _three_way_ctk_case(
            case_id="classify-1pga-three-way-consistency-local-esmfold2",
            esmfold2_confidence_binding_id="contract_test.local_esmfold2_confidence_source.fixture",
            esmfold2_confidence_fact_binding_id="contract_test.local_esmfold2_confidence_fact_source.fixture",
        ),
        _inserted_loop_ctk_case(),
        _inserted_loop_ctk_case(
            case_id="evaluate-inserted-loop-local-esmfold2",
            confidence_binding_id="contract_test.local_inserted_loop_confidence_source.fixture",
            confidence_fact_binding_id="contract_test.local_esmfold2_confidence_fact_source.fixture",
        ),
    ),
    ids=lambda case: case.case_id,
)
def test_structure_comparison_contract_test_kit(
    tmp_path: Path, case: ModulePackageContractCase
) -> None:
    support = (
        TRANSFORM_PACKAGE,
        SOURCE_PACKAGE,
        COLLECTION_OPS_PACKAGE,
        STRUCTURE_PREDICTION_PACKAGE,
    )
    result = execute_module_package_case(
        MODULE_PACKAGE, case, supporting_registrations=support, work_root=tmp_path
    )
    assert result.projection.status == "succeeded"
    if case.node_type_id in {
        "structure_comparison.rmsd_from_alignments",
        "structure_comparison.tm_score_from_alignments",
    }:
        (scores,) = result.outputs["scores"]
        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 2
        assert all((isinstance(entry, ScoreObservation) for entry in scores.entries))
    if case.node_type_id == "structure_comparison.evaluate_inserted_loop":
        (candidates,) = result.outputs["passing_candidates"]
        assert isinstance(candidates, CandidateCollection)
        assert len(candidates.items) == 1
        assert all(
            (
                candidate.candidate_id.startswith("candidate-")
                for candidate in candidates.items
            )
        )


@pytest.mark.parametrize("port_index", range(3))
def test_structure_comparison_contract_test_kit_ports(port_index: int) -> None:
    axis = _axis("S", "AA", ((1.0, 0.0, 0.0), (2.0, 0.0, 0.0)))
    reference_axis = _axis("R", "AA", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
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
    support = (
        TRANSFORM_PACKAGE,
        SOURCE_PACKAGE,
        COLLECTION_OPS_PACKAGE,
        STRUCTURE_PREDICTION_PACKAGE,
    )
    catalog = build_frozen_catalog((MODULE_PACKAGE, *support))

    def reference(kind: str, contract_id: str) -> ExactContractReference:
        return ExactContractReference(
            **catalog.require_contract(kind, contract_id).reference()
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
            reference("method", "folding.fold.esmfold2_fast_biohub_2026_05"),
            90.0,
            True,
            "sha256:" + "9" * 64,
        ),
        ThreeWayConfidenceEvidence(
            "simplefold",
            simplefold_reference,
            reference("method", "folding.fold.simplefold_100m_c7a5570"),
            90.0,
            True,
            "sha256:" + "a" * 64,
        ),
    )
    edges = tuple(
        (
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
                ("input_esmfold2", esmfold2_reference, input_reference, "b", "c", "d"),
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
    )
    consistency = ThreeWayConsistencyEvidence(
        input_structure=input_reference,
        sequence_parent=sequence_reference,
        esmfold2_structure=esmfold2_reference,
        simplefold_structure=simplefold_reference,
        classification_method=reference(
            "method", "structure_comparison.three_way_consistency.threshold_graph"
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
    port_case = (
        ModulePackagePortCase(
            "structure_comparison.alignment_evidence",
            evidence,
            (object(), replace(evidence, correspondence=())),
        ),
        ModulePackagePortCase(
            "structure_comparison.three_way_consistency",
            consistency,
            (object(), replace(consistency, classification="all_disagree")),
        ),
        inserted_loop_port_case,
    )[port_index]
    verify_module_package_port(
        MODULE_PACKAGE, port_case, supporting_registrations=support
    )
