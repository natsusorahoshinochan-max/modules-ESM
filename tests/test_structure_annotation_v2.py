"""Public v2 contracts for the cohesive structure-annotation package."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    InputContentDigests,
    ModulePackageContractCase,
    ModulePackagePortCase,
    OperationCall,
    ProjectManager,
    PortValueError,
    ResultReplaySource,
    V2RunError,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    build_discovered_frozen_catalog,
    discover_module_packages,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    ProteinStructure,
    ResidueLayout,
)
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from modules.structure_annotation import (
    DSSPAnnotation,
    StructureAnnotationTrack,
)
from modules.structure_annotation.implementation import (
    DSSPComputeOperation,
    SASAComputeOperation,
    SecondaryStructureAgreementOperation,
    SecondaryStructureExtractOperation,
)
from modules.structure_annotation.package import (
    MODULE_PACKAGE as STRUCTURE_ANNOTATION_PACKAGE,
)
from modules.structure_transform import (
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.implementation import resolve_residue_axis
from tests.fixtures.structure_transform_sources.package import _FIXTURES


def _candidate_reference(
    candidate_id: str,
    *,
    digest_symbol: str = "a",
    data_type_id: str = "protein.structure",
) -> CandidateDataReference:
    return CandidateDataReference(
        candidate_id=candidate_id,
        data_type_id=data_type_id,
        content_digest="sha256:" + (digest_symbol * 64),
    )


class _InvocationRecorder:
    def __init__(self) -> None:
        self.invocations = 0

    @contextmanager
    def engine_invocation(self, **kwargs: Any):
        del kwargs
        self.invocations += 1
        yield


def _prompt_authoring_packages():
    from modules.prompt_authoring.package import MODULE_PACKAGE as PROMPT_PACKAGE
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    return (PROMPT_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)


def test_structure_annotation_is_one_package_with_seven_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["structure_annotation"]
    assert registration.package_module == "modules.structure_annotation"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/dssp_compute.yaml",
        "definitions/secondary_structure_extract.yaml",
        "definitions/sasa_compute.yaml",
        "definitions/secondary_structure_agreement.yaml",
        "definitions/apply_secondary_structure_to_prompt.yaml",
        "definitions/apply_sasa_to_prompt.yaml",
        "definitions/expected_secondary_structure_from_prompt.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "structure_annotation"
        in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("structure_annotation.dssp_compute", "6.0.0"),
        ("structure_annotation.secondary_structure_extract", "4.0.0"),
        ("structure_annotation.sasa_compute", "4.0.0"),
        ("structure_annotation.secondary_structure_agreement", "5.0.0"),
        (
            "structure_annotation.apply_secondary_structure_to_prompt",
            "5.0.0",
        ),
        ("structure_annotation.apply_sasa_to_prompt", "5.0.0"),
        (
            "structure_annotation.expected_secondary_structure_from_prompt",
            "5.0.0",
        ),
    }


def test_repository_capability_agreement_tracks_distinct_bound_participants(
) -> None:
    workflow = json.loads(
        Path("examples/v2/repository-capabilities.workflow.json").read_text(
            encoding="utf-8"
        )
    )
    incoming = {
        (edge["target_node_id"], edge["target_port"]): (
            edge["source_node_id"],
            edge["source_port"],
        )
        for edge in workflow["edges"]
    }
    agreement = (
        "structure-annotation-secondary-structure-agreement-direct"
    )
    subject_source = incoming[(agreement, "subjects")]
    reference_source = incoming[(agreement, "references")]
    observed_source = incoming[(agreement, "observed")]
    expected_source = incoming[(agreement, "expected")]

    assert observed_source != expected_source
    assert subject_source == (
        "folding-fold-esmfold2-remote",
        "structure_candidates",
    )
    assert reference_source == (
        "protein-io-import-structure-direct",
        "structure_candidates",
    )
    assert incoming[(agreement, "subject_residue_axes")] == (
        "structure-transform-resolve-candidate-residue-axes-esmfold-direct",
        "residue_axes",
    )
    assert incoming[(observed_source[0], "annotations")] == (
        "structure-annotation-dssp-compute-subject-mkdssp-local",
        "annotations",
    )
    assert expected_source == (
        "structure-annotation-expected-secondary-structure-from-prompt-direct",
        "secondary_structure_track",
    )
    assert incoming[(expected_source[0], "references")] == reference_source
    reference_prompt_source = incoming[(expected_source[0], "protein_prompt")]
    assert reference_prompt_source == (
        "structure-annotation-apply-secondary-structure-to-prompt-direct",
        "protein_prompt",
    )
    reference_track_source = incoming[
        (reference_prompt_source[0], "secondary_structure_track")
    ]
    assert reference_track_source == (
        "structure-annotation-secondary-structure-extract-direct",
        "secondary_structure_track",
    )
    assert incoming[(reference_track_source[0], "annotations")] == (
        "structure-annotation-dssp-compute-mkdssp-local",
        "annotations",
    )
    assert incoming[
        (
            "structure-annotation-dssp-compute-subject-mkdssp-local",
            "structure_candidates",
        )
    ] == subject_source
    assert incoming[
        (
            "structure-annotation-dssp-compute-subject-mkdssp-local",
            "residue_axes",
        )
    ] == (
        "structure-transform-resolve-candidate-residue-axes-esmfold-direct",
        "residue_axes",
    )
    assert incoming[
        (
            "structure-annotation-dssp-compute-mkdssp-local",
            "structure_candidates",
        )
    ] == reference_source
    assert incoming[
        (
            "structure-annotation-dssp-compute-mkdssp-local",
            "residue_axes",
        )
    ] == (
        "structure-transform-resolve-candidate-residue-axes-imported-direct",
        "residue_axes",
    )


def test_structure_annotation_publishes_one_active_contract_generation() -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )

    methods = {
        (contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind == "method"
        and contract.contract_id.startswith("structure_annotation.")
    }
    assert methods == {
        ("structure_annotation.dssp_compute.method", "3.0.0"),
        (
            "structure_annotation.secondary_structure_extract.method",
            "3.0.0",
        ),
        ("structure_annotation.sasa_compute.method", "3.0.0"),
        (
            "structure_annotation.secondary_structure_agreement.method",
            "3.0.0",
        ),
        (
            "structure_annotation.apply_secondary_structure_to_prompt.method",
            "2.2.0",
        ),
        ("structure_annotation.apply_sasa_to_prompt.method", "2.2.0"),
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.method",
            "3.0.0",
        ),
    }
    ports = {
        (port_type.type_id, port_type.version)
        for port_type in catalog.port_types
        if port_type.type_id.startswith("structure_annotation.")
    }
    assert ports == {
        ("structure_annotation.dssp_annotations", "4.0.0"),
        ("structure_annotation.secondary_structure_track", "4.0.0"),
        ("structure_annotation.sasa_track", "4.0.0"),
    }
    agreement_metric = catalog.require_contract(
        "metric",
        "structure_annotation.secondary_structure_agreement",
        "3.0.0",
    )
    assert agreement_metric.descriptor["aggregation_semantics"] == {
        "kind": "equal_weight_fraction",
        "source_metric": (
            "structure_annotation.secondary_structure.position_agreement@3.0.0"
        ),
        "included_values": (
            "residues_with_present_exact_SS8_on_both_tracks"
        ),
    }
    position_metric = catalog.require_contract(
        "metric",
        "structure_annotation.secondary_structure.position_agreement",
        "3.0.0",
    )
    assert position_metric.descriptor["value_shape"] == "per_residue"
    for method_id, method_version in methods:
        method = catalog.require_contract(
            "method",
            method_id,
            method_version,
        )
        assert b"@2.1.0" not in canonical_json_bytes(
            method.descriptor["featurization_identity"]
        )

    bindings = {
        (contract.contract_id, contract.contract_version): contract
        for contract in catalog.contracts
        if contract.contract_kind == "binding"
        and contract.contract_id.startswith("structure_annotation.")
    }
    assert set(bindings) == {
        ("structure_annotation.dssp_compute.mkdssp_local", "6.0.0"),
        (
            "structure_annotation.secondary_structure_extract.direct",
            "4.0.0",
        ),
        ("structure_annotation.sasa_compute.direct", "4.0.0"),
        (
            "structure_annotation.secondary_structure_agreement.direct",
            "5.0.0",
        ),
        (
            "structure_annotation.apply_secondary_structure_to_prompt.direct",
            "5.0.0",
        ),
        ("structure_annotation.apply_sasa_to_prompt.direct", "5.0.0"),
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct",
            "5.0.0",
        ),
    }
    for binding_id, binding in bindings.items():
        assert binding.descriptor["node_type"]["contract_version"] == (
            binding_id[1]
        )
        assert binding.descriptor["method"]["contract_version"] == (
            "3.0.0"
            if binding_id[0]
            in {
                "structure_annotation.dssp_compute.mkdssp_local",
                "structure_annotation.secondary_structure_extract.direct",
                "structure_annotation.sasa_compute.direct",
                "structure_annotation.secondary_structure_agreement.direct",
                (
                    "structure_annotation."
                    "expected_secondary_structure_from_prompt.direct"
                ),
            }
            else "2.2.0"
        )


def test_annotation_ports_preserve_multichain_layout_missing_and_ss8() -> None:
    port_types = {
        (port_type.type_id, port_type.version): port_type
        for port_type in STRUCTURE_ANNOTATION_PACKAGE.port_types
    }
    subject = _candidate_reference("subject-structure")
    layout = ResidueLayout(
        chain_id="A,B",
        length=4,
        residue_ids=["A:4", "A:6", "B:1", "B:2"],
    )
    annotation = DSSPAnnotation(
        subject=subject,
        layout=layout,
        secondary_structure=("G", "_", "C", "E"),
        sasa=(14.5, None, 0.0, 91.25),
    )
    annotation_type = port_types[(
        "structure_annotation.dssp_annotations",
        "4.0.0",
    )]
    secondary_type = port_types[(
        "structure_annotation.secondary_structure_track",
        "4.0.0",
    )]

    assert annotation_type.decode(annotation_type.encode(annotation)) == annotation
    track = StructureAnnotationTrack(
        subject=subject,
        layout=layout,
        values=annotation.secondary_structure,
    )
    assert secondary_type.decode(secondary_type.encode(track)) == track
    wire = json.loads(secondary_type.encode(track))["value"]
    assert wire["track"]["fields"]["values"] == ["G", "_", "C", "E"]

    with pytest.raises(PortValueError, match="unsupported alphabet"):
        secondary_type.encode(
            StructureAnnotationTrack(
                subject=subject,
                layout=layout,
                values=("H", "-", "E", "C"),
            )
        )


def test_annotation_wire_requires_subject_and_subject_changes_content_identity(
) -> None:
    port_types = {
        (port_type.type_id, port_type.version): port_type
        for port_type in STRUCTURE_ANNOTATION_PACKAGE.port_types
    }
    layout = ResidueLayout(
        chain_id="A",
        length=1,
        residue_ids=["A:1"],
    )
    annotation_type = port_types[(
        "structure_annotation.dssp_annotations",
        "4.0.0",
    )]
    track_type = port_types[(
        "structure_annotation.secondary_structure_track",
        "4.0.0",
    )]
    first_subject = _candidate_reference("subject-1", digest_symbol="a")
    same_id_new_content = _candidate_reference(
        "subject-1",
        digest_symbol="b",
    )
    same_content_new_id = _candidate_reference(
        "subject-2",
        digest_symbol="a",
    )

    annotations = tuple(
        DSSPAnnotation(
            subject=subject,
            layout=layout,
            secondary_structure=("H",),
            sasa=(10.0,),
        )
        for subject in (
            first_subject,
            same_id_new_content,
            same_content_new_id,
        )
    )
    tracks = tuple(
        StructureAnnotationTrack(
            subject=subject,
            layout=layout,
            values=("H",),
        )
        for subject in (
            first_subject,
            same_id_new_content,
            same_content_new_id,
        )
    )

    assert len(
        {annotation_type.content_digest(value) for value in annotations}
    ) == 3
    assert len({track_type.content_digest(value) for value in tracks}) == 3
    assert annotation_type.decode(annotation_type.encode(annotations[0])) == (
        annotations[0]
    )
    assert track_type.decode(track_type.encode(tracks[0])) == tracks[0]

    legacy_wire = json.loads(annotation_type.encode(annotations[0]))
    del legacy_wire["value"]["subject"]
    with pytest.raises(PortValueError, match="wire value is not closed"):
        annotation_type.decode(canonical_json_bytes(legacy_wire))

    legacy_track_wire = json.loads(track_type.encode(tracks[0]))
    del legacy_track_wire["value"]["subject"]
    with pytest.raises(PortValueError, match="wire value is not closed"):
        track_type.decode(canonical_json_bytes(legacy_track_wire))


def test_dssp_operation_crosses_one_canonical_only_adapter_interface() -> None:
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    subject = _candidate_reference("subject-structure")
    axis = resolve_residue_axis(structure)
    associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=subject,
                residue_axis=axis,
            ),
        )
    )
    annotation = DSSPAnnotation(
        subject=subject,
        layout=ResidueLayout(
            chain_id="A",
            length=1,
            residue_ids=["A:1"],
        ),
        secondary_structure=("C",),
        sasa=(10.0,),
    )

    class RecordingAdapter:
        def __init__(self) -> None:
            self.calls: list[
                tuple[object, CandidateDataReference]
            ] = []

        def annotate(
            self,
            value: object,
            *,
            subject: CandidateDataReference,
        ) -> DSSPAnnotation:
            self.calls.append((value, subject))
            return annotation

    adapter = RecordingAdapter()
    operation = DSSPComputeOperation(adapter)
    candidates = CandidateCollection(
        collection_id="subject-structures",
        item_type="protein.structure",
        items=[Candidate(candidate_id=subject.candidate_id, data=structure)],
    )
    output = operation.execute(
        OperationCall(
            inputs={
                "structure_candidates": candidates,
                "residue_axes": associations,
            },
            node_parameters={},
            binding_parameters={},
            input_content_digests={
                "structure_candidates": InputContentDigests(
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + ("f" * 64),),
                    candidate_data=(subject,),
                )
            },
        )
    )

    assert adapter.calls == [(axis, subject)]
    assert output == {"annotations": annotation}


def test_dssp_requires_singleton_protein_structure_candidate_reference() -> None:
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    subject = _candidate_reference("subject-structure")

    class ForbiddenAdapter:
        def annotate(self, *args: Any, **kwargs: Any) -> DSSPAnnotation:
            raise AssertionError("adapter must not run before admission")

    operation = DSSPComputeOperation(ForbiddenAdapter())
    candidates = CandidateCollection(
        collection_id="subject-structures",
        item_type="protein.structure",
        items=[Candidate(candidate_id=subject.candidate_id, data=structure)],
    )

    with pytest.raises(ValueError, match="exact Candidate content identity"):
        operation.execute(
            OperationCall(
                inputs={
                    "structure_candidates": candidates,
                    "residue_axes": CandidateResolvedResidueAxisAssociations(
                        entries=(
                            CandidateResolvedResidueAxisAssociation(
                                subject,
                                resolve_residue_axis(structure),
                            ),
                        )
                    ),
                },
                node_parameters={},
                binding_parameters={},
                input_content_digests={
                    "structure_candidates": InputContentDigests(
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + ("f" * 64),),
                        candidate_data=(
                            _candidate_reference(
                                "another-candidate",
                                digest_symbol="b",
                            ),
                        ),
                    )
                },
            )
        )


def test_dssp_requires_one_exact_residue_axis_association_before_adapter() -> None:
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    subject = _candidate_reference("subject-structure")
    candidates = CandidateCollection(
        collection_id="subject-structures",
        item_type="protein.structure",
        items=[Candidate(candidate_id=subject.candidate_id, data=structure)],
    )

    class ForbiddenAdapter:
        def annotate(self, *args: Any, **kwargs: Any) -> DSSPAnnotation:
            raise AssertionError("adapter must not run before exact axis join")

    operation = DSSPComputeOperation(ForbiddenAdapter())
    wrong_subject = _candidate_reference(
        subject.candidate_id,
        digest_symbol="b",
    )
    wrong_associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=wrong_subject,
                residue_axis=resolve_residue_axis(structure),
            ),
        )
    )
    with pytest.raises(
        ValueError,
        match="one exact resolved residue-axis association",
    ):
        operation.execute(
            OperationCall(
                inputs={
                    "structure_candidates": candidates,
                    "residue_axes": wrong_associations,
                },
                node_parameters={},
                binding_parameters={},
                input_content_digests={
                    "structure_candidates": InputContentDigests(
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + ("f" * 64),),
                        candidate_data=(subject,),
                    )
                },
            )
        )


def test_dssp_receives_authoritative_three_residue_axis_including_mse() -> None:
    structure = ProteinStructure(_FIXTURES["mse_ligand_water"]())
    subject = _candidate_reference("mse-structure")
    axis = resolve_residue_axis(structure)
    associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(subject, axis),
        )
    )
    annotation = DSSPAnnotation(
        subject=subject,
        layout=axis.layout,
        secondary_structure=("C", "C", "C"),
        sasa=(1.0, 2.0, 3.0),
    )

    class RecordingAdapter:
        def __init__(self) -> None:
            self.axes: list[object] = []

        def annotate(
            self,
            value: object,
            *,
            subject: CandidateDataReference,
        ) -> DSSPAnnotation:
            assert subject == annotation.subject
            self.axes.append(value)
            return annotation

    adapter = RecordingAdapter()
    output = DSSPComputeOperation(adapter).execute(
        OperationCall(
            inputs={
                "structure_candidates": CandidateCollection(
                    collection_id="mse-structures",
                    item_type="protein.structure",
                    items=[Candidate(subject.candidate_id, structure)],
                ),
                "residue_axes": associations,
            },
            node_parameters={},
            binding_parameters={},
            input_content_digests={
                "structure_candidates": InputContentDigests(
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + ("f" * 64),),
                    candidate_data=(subject,),
                )
            },
        )
    )

    assert adapter.axes == [axis]
    assert axis.layout.residue_ids == ("A:1", "A:2", "A:3")
    assert axis.residue_names == ("ALA", "MET", "GLY")
    assert output == {"annotations": annotation}


def test_secondary_structure_and_sasa_extraction_preserve_subject() -> None:
    subject = _candidate_reference("subject-structure")
    annotation = DSSPAnnotation(
        subject=subject,
        layout=ResidueLayout(
            chain_id="A",
            length=2,
            residue_ids=["A:1", "A:2"],
        ),
        secondary_structure=("P", "H"),
        sasa=(12.0, None),
    )
    call = OperationCall(
        inputs={"annotations": annotation},
        node_parameters={},
        binding_parameters={},
        input_content_digests={},
    )

    secondary = SecondaryStructureExtractOperation(
        _InvocationRecorder()
    ).execute(call)["secondary_structure_track"]
    sasa = SASAComputeOperation(_InvocationRecorder()).execute(call)[
        "sasa_track"
    ]

    assert secondary.subject == subject
    assert secondary.values == ("C", "H")
    assert sasa.subject == subject
    assert sasa.values == (12.0, None)


@pytest.mark.parametrize(
    "mismatch_kind",
    (
        "same-id-different-digest",
        "same-digest-different-id",
        "different-id-and-digest",
        "different-data-type",
    ),
)
@pytest.mark.parametrize("track_role", ("observed", "expected"))
def test_agreement_rejects_track_candidate_mismatch_before_engine(
    mismatch_kind: str,
    track_role: str,
) -> None:
    resources = _InvocationRecorder()
    operation = SecondaryStructureAgreementOperation(
        resources=resources,
        method=ExactContractReference(
            contract_kind="method",
            contract_id=(
                "structure_annotation.secondary_structure_agreement.method"
            ),
            contract_version="3.0.0",
            contract_digest="sha256:" + ("d" * 64),
        ),
        produced_observations=(),
    )
    layout = ResidueLayout(
        chain_id="A",
        length=1,
        residue_ids=["A:1"],
    )
    subject_reference = _candidate_reference("subject-1", digest_symbol="a")
    expected_reference = _candidate_reference(
        "reference-1",
        digest_symbol="c",
    )
    admitted_reference = (
        subject_reference if track_role == "observed" else expected_reference
    )
    mismatched_reference = CandidateDataReference(
        candidate_id=(
            admitted_reference.candidate_id
            if mismatch_kind
            in {"same-id-different-digest", "different-data-type"}
            else admitted_reference.candidate_id + "-other"
        ),
        data_type_id=(
            "protein.sequence"
            if mismatch_kind == "different-data-type"
            else admitted_reference.data_type_id
        ),
        content_digest=(
            admitted_reference.content_digest
            if mismatch_kind
            in {"same-digest-different-id", "different-data-type"}
            else "sha256:" + ("d" * 64)
        ),
    )
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    subjects = CandidateCollection(
        collection_id="subjects",
        item_type="protein.structure",
        items=[Candidate(candidate_id="subject-1", data=structure)],
    )
    references = CandidateCollection(
        collection_id="references",
        item_type="protein.structure",
        items=[Candidate(candidate_id="reference-1", data=structure)],
    )
    subject_residue_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject_reference,
                resolve_residue_axis(structure),
            ),
        )
    )
    call = OperationCall(
        inputs={
            "subjects": subjects,
            "references": references,
            "expected": StructureAnnotationTrack(
                subject=(
                    mismatched_reference
                    if track_role == "expected"
                    else expected_reference
                ),
                layout=layout,
                values=("H",),
            ),
            "observed": StructureAnnotationTrack(
                subject=(
                    mismatched_reference
                    if track_role == "observed"
                    else subject_reference
                ),
                layout=layout,
                values=("H",),
            ),
            "subject_residue_axes": subject_residue_axes,
        },
        node_parameters={},
        binding_parameters={},
        input_content_digests={
            "subjects": InputContentDigests(
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + ("e" * 64),),
                candidate_data=(subject_reference,),
            ),
            "references": InputContentDigests(
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + ("f" * 64),),
                candidate_data=(expected_reference,),
            ),
        },
    )

    with pytest.raises(ValueError, match=f"{track_role} track subject"):
        operation.execute(call)
    assert resources.invocations == 0


def test_agreement_checks_layout_after_exact_participant_binding() -> None:
    resources = _InvocationRecorder()
    operation = SecondaryStructureAgreementOperation(
        resources=resources,
        method=ExactContractReference(
            contract_kind="method",
            contract_id=(
                "structure_annotation.secondary_structure_agreement.method"
            ),
            contract_version="3.0.0",
            contract_digest="sha256:" + ("d" * 64),
        ),
        produced_observations=(),
    )
    subject = _candidate_reference("subject-1")
    reference = _candidate_reference("reference-1", digest_symbol="c")
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    inputs = {
        "subjects": CandidateCollection(
            collection_id="subjects",
            item_type="protein.structure",
            items=[Candidate(candidate_id=subject.candidate_id, data=structure)],
        ),
        "references": CandidateCollection(
            collection_id="references",
            item_type="protein.structure",
            items=[
                Candidate(candidate_id=reference.candidate_id, data=structure)
            ],
        ),
        "expected": StructureAnnotationTrack(
            subject=reference,
            layout=ResidueLayout("A", 1, ["A:1"]),
            values=("H",),
        ),
        "observed": StructureAnnotationTrack(
            subject=subject,
            layout=ResidueLayout("A", 1, ["A:2"]),
            values=("H",),
        ),
        "subject_residue_axes": CandidateResolvedResidueAxisAssociations(
            entries=(
                CandidateResolvedResidueAxisAssociation(
                    subject,
                    resolve_residue_axis(structure),
                ),
            )
        ),
    }

    with pytest.raises(ValueError, match="one identical exact layout"):
        operation.execute(
            OperationCall(
                inputs=inputs,
                node_parameters={},
                binding_parameters={},
                input_content_digests={
                    "subjects": InputContentDigests(
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + ("e" * 64),),
                        candidate_data=(subject,),
                    ),
                    "references": InputContentDigests(
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + ("f" * 64),),
                        candidate_data=(reference,),
                    ),
                },
            )
        )
    assert resources.invocations == 0


def test_agreement_requires_exact_subject_axis_join_before_engine() -> None:
    resources = _InvocationRecorder()
    operation = SecondaryStructureAgreementOperation(
        resources=resources,
        method=ExactContractReference(
            contract_kind="method",
            contract_id=(
                "structure_annotation.secondary_structure_agreement.method"
            ),
            contract_version="3.0.0",
            contract_digest="sha256:" + ("d" * 64),
        ),
        produced_observations=(),
    )
    subject = _candidate_reference("subject-1")
    reference = _candidate_reference("reference-1", digest_symbol="c")
    wrong_subject = _candidate_reference(
        subject.candidate_id,
        digest_symbol="b",
    )
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    layout = ResidueLayout("A", 1, ("A:1",))
    with pytest.raises(
        ValueError,
        match="one exact resolved residue-axis association",
    ):
        operation.execute(
            OperationCall(
                inputs={
                    "subjects": CandidateCollection(
                        "subjects",
                        "protein.structure",
                        (Candidate(subject.candidate_id, structure),),
                    ),
                    "references": CandidateCollection(
                        "references",
                        "protein.structure",
                        (Candidate(reference.candidate_id, structure),),
                    ),
                    "expected": StructureAnnotationTrack(
                        reference,
                        layout,
                        ("H",),
                    ),
                    "observed": StructureAnnotationTrack(
                        subject,
                        layout,
                        ("H",),
                    ),
                    "subject_residue_axes": (
                        CandidateResolvedResidueAxisAssociations(
                            entries=(
                                CandidateResolvedResidueAxisAssociation(
                                    wrong_subject,
                                    resolve_residue_axis(structure),
                                ),
                            )
                        )
                    ),
                },
                node_parameters={},
                binding_parameters={},
                input_content_digests={
                    "subjects": InputContentDigests(
                        "candidate.collection",
                        ("sha256:" + ("e" * 64),),
                        (subject,),
                    ),
                    "references": InputContentDigests(
                        "candidate.collection",
                        ("sha256:" + ("f" * 64),),
                        (reference,),
                    ),
                },
            )
        )
    assert resources.invocations == 0


def test_dssp_binary_is_binding_environment_not_workflow_parameter() -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )
    node = catalog.require_contract(
        "node_type",
        "structure_annotation.dssp_compute",
        "6.0.0",
    )
    binding = catalog.require_contract(
        "binding",
        "structure_annotation.dssp_compute.mkdssp_local",
        "6.0.0",
    )

    assert node.descriptor["node_parameters"] == {}
    assert binding.descriptor["binding_parameters"] == {}
    assert binding.descriptor["execution_route"] == "adapter"
    assert binding.descriptor["route_behavior"] == {
        "behavior_id": "structure_annotation.mkdssp_local/adapter",
        "behavior_version": "6.0.0",
        "parameters": {
            "axis_source": (
                "exact-candidate-associated-authoritative-"
                "resolved-residue-axis"
            ),
            "binary": "mkdssp",
            "binary_version": "4.6.1",
            "provider_contract": "PDB-REDO/dssp@v4.6.1",
            "request_format": "PDB-v3.3-fixed-columns",
            "residue_reconciliation": (
                "dssp-summary-label-pair-via-atom-site-auth-fields-"
                "to-authoritative-axis-exact-identity"
            ),
            "response_format": "mkdssp-4.6.1-mmCIF",
            "source_archive_sha256": (
                "5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3"
            ),
        },
    }
    provider_identity = binding.descriptor["implementation_identity"][
        "provider_identity"
    ]
    assert provider_identity == {
        "repository": "PDB-REDO/dssp",
        "source_revision": "v4.6.1",
        "source_archive_sha256": (
            "5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3"
        ),
        "binary": "mkdssp",
        "binary_version": "4.6.1",
    }
    method_reference = binding.descriptor["method"]
    method = catalog.require_contract(
        method_reference["contract_kind"],
        method_reference["contract_id"],
        method_reference["contract_version"],
    )
    assert method.descriptor["source_identity"] == provider_identity
    prerequisites = binding.descriptor["readiness_declaration"][
        "prerequisites"
    ]
    assert prerequisites["binary"] == {
        "name": "mkdssp",
        "path_source": "trusted_environment_configuration",
        "required_version": "4.6.1",
    }
    assert binding.descriptor["availability_declaration"][
        "prerequisites"
    ] == {
        "binary_configuration": {
            "name": "mkdssp",
            "path_source": "trusted_environment_configuration",
        }
    }
    published = binding.descriptor_bytes.decode("utf-8")
    assert "dssp_binary" not in published
    assert "/opt/" not in published


def test_only_mkdssp_compute_crosses_an_adapter_route() -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )
    bindings = {
        contract.contract_id: contract
        for contract in catalog.contracts
        if contract.contract_kind == "binding"
        and contract.contract_id.startswith("structure_annotation.")
    }

    assert set(bindings) == {
        "structure_annotation.dssp_compute.mkdssp_local",
        "structure_annotation.secondary_structure_extract.direct",
        "structure_annotation.sasa_compute.direct",
        "structure_annotation.secondary_structure_agreement.direct",
        "structure_annotation.apply_secondary_structure_to_prompt.direct",
        "structure_annotation.apply_sasa_to_prompt.direct",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct"
        ),
    }
    assert bindings[
        "structure_annotation.dssp_compute.mkdssp_local"
    ].descriptor["execution_route"] == "adapter"
    for binding_id in (
        "structure_annotation.secondary_structure_extract.direct",
        "structure_annotation.sasa_compute.direct",
        "structure_annotation.secondary_structure_agreement.direct",
        "structure_annotation.apply_secondary_structure_to_prompt.direct",
        "structure_annotation.apply_sasa_to_prompt.direct",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct"
        ),
    ):
        descriptor = bindings[binding_id].descriptor
        assert descriptor["execution_route"] == "direct"
        assert "adapter" not in descriptor["implementation_identity"]


def _fake_dssp_binary(
    path: Path,
    *,
    output: str | None,
    exit_code: int = 0,
    version: str = "4.6.1",
) -> Path:
    binary = path / "mkdssp-fixture"
    output_command = (
        "printf '\\377'\n"
        if output is None
        else "cat <<'DSSP_OUTPUT'\n" + output + "DSSP_OUTPUT\n"
    )
    binary.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        f"  printf '%s\\n' 'mkdssp version {version}'\n"
        "  exit 0\n"
        "fi\n"
        f"{output_command}"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


def _decode_output(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _run_dssp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pdb_text: str,
    dssp_output: str | None,
    configured_binary: str | None = None,
    result_replay_source: ResultReplaySource | None = None,
    binary_version: str = "4.6.1",
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...], str]:
    binary = _fake_dssp_binary(
        tmp_path,
        output=dssp_output,
        version=binary_version,
    )
    catalog = build_frozen_catalog(
        (
            PROTEIN_IO_PACKAGE,
            STRUCTURE_ANNOTATION_PACKAGE,
            *_prompt_authoring_packages(),
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("structure annotation DSSP")
    projects.publish_input(
        project.id,
        "structure-input",
        pdb_text.encode("ascii"),
        filename="structure-input.pdb",
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="import",
                node_type_id="protein_io.import_structure",
                node_type_version="5.0.0",
                binding_id="protein_io.import_structure.direct",
                binding_version="5.0.0",
                node_parameters={"project_input_ref": "structure-input"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="resolve-axis",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                node_type_version="5.0.0",
                binding_id=(
                    "structure_transform."
                    "resolve_candidate_residue_axes.direct"
                ),
                binding_version="5.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="annotate",
                node_type_id="structure_annotation.dssp_compute",
                node_type_version="6.0.0",
                binding_id="structure_annotation.dssp_compute.mkdssp_local",
                binding_version="6.0.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "import",
                "structure_candidates",
                "resolve-axis",
                "structure_candidates",
            ),
            WorkflowEdge(
                "import",
                "structure_candidates",
                "annotate",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-axis",
                "residue_axes",
                "annotate",
                "residue_axes",
            ),
        ),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )
    authoring.require_compiled(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (
                    "structure_annotation.dssp_compute.mkdssp_local",
                    "6.0.0",
                ): {
                    "values": {
                        "dssp_binary": configured_binary or str(binary)
                    },
                    "safe_fingerprint": "mkdssp-fixture-4.6.1",
                    "invalidation_token": "mkdssp-fixture-4.6.1",
                }
            }
        ),
        result_replay_source,
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="structure-annotation-dssp",
        )
    except BaseException:
        service.shutdown()
        raise
    service.shutdown()
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    return catalog, service, projection, events, str(binary)


def _pdb_ca_line(
    serial: int,
    residue_name: str,
    chain_id: str,
    residue_number: int,
    insertion_code: str,
) -> str:
    line = (
        f"{'ATOM':<6}{serial:5d} {'CA':^4} {residue_name:>3} "
        f"{chain_id}{residue_number:4d}{insertion_code:1}   "
        f"{float(serial):8.3f}{2.0:8.3f}{3.0:8.3f}"
        f"{'  1.00'}{' 20.00'}{'':10}{' C'}{'  '}"
    )
    assert len(line) == 80
    return line


def test_dssp_compute_joins_label_ids_through_atom_site_to_exact_authored_axis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    residues = (
        ("GLY", "A", -3, "A"),
        ("ALA", "A", 0, ""),
        ("ILE", "A", 1, ""),
        ("THR", "A", 2, ""),
        ("GLU", "A", 3, ""),
        ("ASN", "B", 10, ""),
        ("SER", "B", 10, "A"),
        ("PRO", "B", 11, ""),
        ("CYS", "B", 12, ""),
    )
    pdb_text = "\n".join(
        (
            *(
                _pdb_ca_line(index, *residue)
                for index, residue in enumerate(residues[:5], start=1)
            ),
            "TER",
            *(
                _pdb_ca_line(index, *residue)
                for index, residue in enumerate(residues[5:], start=6)
            ),
            "TER",
            "END",
            "",
        )
    )
    dssp_output = """\
data_fixture
loop_
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
X 1 A -3 A
X 2 A 0 ?
X 3 A 1 ?
X 4 A 2 ?
X 5 A 3 ?
Y 1 B 10 ?
Y 2 B 10 A
Y 3 B 11 ?
Y 4 B 12 ?
#
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
fixture X 1 GLY G 1.25
fixture X 2 ALA H 0.0
fixture X 3 ILE I ?
fixture X 4 THR T 35.5
fixture X 5 GLU E .
fixture Y 1 ASN B 100.0
fixture Y 2 SER S 7.75
fixture Y 3 PRO P 12.0
fixture Y 4 CYS . 9.5
#
"""

    catalog, service, projection, events, private_path = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=pdb_text,
        dssp_output=dssp_output,
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
    )
    axis_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "resolve-axis"
        and item["output_port"] == "residue_axes"
    )
    association = _decode_output(
        catalog,
        service,
        projection,
        axis_output,
    ).entries[0]
    annotation = _decode_output(catalog, service, projection, output)
    assert annotation.subject == association.subject
    assert annotation.layout == association.residue_axis.layout
    assert annotation.layout.residue_ids == (
        "A:-3A",
        "A:0",
        "A:1",
        "A:2",
        "A:3",
        "B:10",
        "B:10A",
        "B:11",
        "B:12",
    )
    assert annotation.secondary_structure == (
        "G",
        "H",
        "I",
        "T",
        "E",
        "B",
        "S",
        "P",
        "C",
    )
    assert annotation.sasa == (
        1.25,
        0.0,
        None,
        35.5,
        None,
        100.0,
        7.75,
        12.0,
        9.5,
    )
    event_types = [event["event"]["type"] for event in events]
    assert event_types.count("engine_invocation_started") == 3
    assert event_types.count("engine_invocation_terminal") == 3
    assert private_path not in json.dumps(
        {"projection": projection, "events": events},
        sort_keys=True,
    )


def test_dssp_compute_requires_complete_authored_axis_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdb_text = "\n".join(
        (
            _pdb_ca_line(1, "GLY", "A", 4, ""),
            _pdb_ca_line(2, "ALA", "A", 6, ""),
            "TER",
            "END",
            "",
        )
    )
    _, _, projection, _, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=pdb_text,
        dssp_output="""\
data_fixture
loop_
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
X 1 A 4 ?
X 2 A 6 ?
#
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
fixture X 1 GLY H 10.0
#
""",
    )

    assert projection["status"] == "failed"
    assert all(
        output["node_id"] != "annotate"
        for output in projection["outputs"]
    )


def test_dssp_reconciles_mse_on_authoritative_three_residue_axis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, service, projection, _, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=_FIXTURES["mse_ligand_water"](),
        dssp_output="""\
data_fixture
loop_
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
A 1 A 1 ?
A 2 A 2 ?
A 3 A 3 ?
#
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 1 ALA H 10.0 2.0 2.0 3.0
fixture A 2 MSE . 20.0 6.0 2.0 3.0
fixture A 3 GLY E 30.0 14.0 2.0 3.0
#
""",
    )

    assert projection["status"] == "succeeded"
    annotation = _decode_output(
        catalog,
        service,
        projection,
        next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "annotate"
        ),
    )
    axis_associations = _decode_output(
        catalog,
        service,
        projection,
        next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "resolve-axis"
            and item["output_port"] == "residue_axes"
        ),
    )
    association = axis_associations.entries[0]
    assert annotation.subject == association.subject
    assert annotation.layout == association.residue_axis.layout
    assert annotation.layout.residue_ids == ("A:1", "A:2", "A:3")
    assert association.residue_axis.residue_names == ("ALA", "MET", "GLY")
    assert annotation.secondary_structure == ("H", "C", "E")
    assert annotation.sasa == (10.0, 20.0, 30.0)


def test_environment_only_binary_path_is_available_and_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, projection, _, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C  \n"
            "TER\nEND\n"
        ),
        dssp_output="""\
data_fixture
loop_
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
A 1 A 1 ?
#
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 1 GLY H 10.0 1.0 2.0 3.0
#
""",
    )

    assert projection["status"] == "succeeded"


def test_dssp_dot_is_coil_and_p_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, service, projection, _, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C  \n"
            "ATOM      2  CA  ALA A   2       "
            "2.000   3.000   4.000  1.00 20.00           C  \n"
            "TER\nEND\n"
        ),
        dssp_output="""\
data_fixture
loop_
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
A 1 A 1 ?
A 2 A 2 ?
#
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
    fixture A 1 GLY . 10.0 1.0 2.0 3.0
    fixture A 2 ALA P 20.0 2.0 3.0 4.0
#
""",
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
    )
    annotation = _decode_output(catalog, service, projection, output)
    assert annotation.secondary_structure == ("C", "P")


def test_dssp_readiness_rejects_version_prefix_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = type(
        "LookupRecorder",
        (ResultReplaySource,),
        {
            "lookups": 0,
            "lookup": lambda self, **kwargs: setattr(
                self,
                "lookups",
                self.lookups + 1,
            ),
        },
    )()

    with pytest.raises(V2RunError) as rejected:
        _run_dssp(
            tmp_path,
            monkeypatch,
            pdb_text=(
                "ATOM      1  CA  GLY A   1       "
                "1.000   2.000   3.000  1.00 20.00           C  \n"
                "TER\nEND\n"
            ),
            dssp_output="unused\n",
            binary_version="4.6.10",
            result_replay_source=cache,
        )

    assert rejected.value.code == "readiness_rejected"
    assert cache.lookups == 0


def test_unready_dssp_rejects_before_cache_lookup_or_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LookupRecorder(ResultReplaySource):
        def __init__(self) -> None:
            self.lookups = 0

        def lookup(self, **kwargs: Any) -> None:
            del kwargs
            self.lookups += 1
            return None

    cache = LookupRecorder()
    with pytest.raises(V2RunError) as rejected:
        _run_dssp(
            tmp_path,
            monkeypatch,
            pdb_text=(
                "ATOM      1  CA  GLY A   1       "
                "1.000   2.000   3.000  1.00 20.00           C  \n"
                "TER\nEND\n"
            ),
            dssp_output="unused\n",
            configured_binary=str(tmp_path / "missing-mkdssp"),
            result_replay_source=cache,
        )

    assert rejected.value.code == "readiness_rejected"
    assert cache.lookups == 0


def test_structure_annotation_passes_ctk_for_all_seven_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.structure_annotation_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    dssp_output = """\
data_fixture
loop_
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
A 1 A 1 ?
A 2 A 2 ?
#
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 1 GLY H 10.0 1.0 2.0 3.0
fixture A 2 ALA . 20.0 2.0 3.0 4.0
#
"""
    binary = _fake_dssp_binary(tmp_path, output=dssp_output)
    candidate_source = WorkflowNodeInstance(
        node_id="candidates",
        node_type_id="contract_test.structure_annotation_candidate_source",
        node_type_version="3.0.0",
        binding_id=(
            "contract_test.structure_annotation_candidate_source.direct"
        ),
        binding_version="3.0.0",
        node_parameters={},
        binding_parameters={},
    )
    residue_axis_resolver = WorkflowNodeInstance(
        node_id="resolve-axis",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        node_type_version="5.0.0",
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        binding_version="5.0.0",
        node_parameters={},
        binding_parameters={},
    )
    value_source = WorkflowNodeInstance(
        node_id="values",
        node_type_id="contract_test.structure_annotation_value_source",
        node_type_version="3.0.0",
        binding_id="contract_test.structure_annotation_value_source.direct",
        binding_version="3.0.0",
        node_parameters={},
        binding_parameters={},
    )
    value_source_edges = (
        WorkflowEdge("candidates", "subjects", "values", "subjects"),
        WorkflowEdge("candidates", "references", "values", "references"),
    )
    cases = (
        ModulePackageContractCase(
            case_id="structure-annotation-dssp",
            node_type_id="structure_annotation.dssp_compute",
            node_type_version="6.0.0",
            binding_id="structure_annotation.dssp_compute.mkdssp_local",
            binding_version="6.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={"dssp_binary": str(binary)},
            safe_environment_fingerprint="mkdssp-fixture-4.6.1",
            invalidation_token="mkdssp-fixture-4.6.1",
            workflow_nodes=(candidate_source, residue_axis_resolver),
            workflow_edges=(
                WorkflowEdge(
                    "candidates",
                    "subjects",
                    "resolve-axis",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "candidates",
                    "subjects",
                    "contract-test-node",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "resolve-axis",
                    "residue_axes",
                    "contract-test-node",
                    "residue_axes",
                ),
            ),
            forbidden_public_fragments=(str(binary),),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-secondary",
            node_type_id="structure_annotation.secondary_structure_extract",
            node_type_version="4.0.0",
            binding_id=(
                "structure_annotation.secondary_structure_extract.direct"
            ),
            binding_version="4.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(candidate_source, value_source),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "values",
                    "annotations",
                    "contract-test-node",
                    "annotations",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-sasa",
            node_type_id="structure_annotation.sasa_compute",
            node_type_version="4.0.0",
            binding_id="structure_annotation.sasa_compute.direct",
            binding_version="4.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(candidate_source, value_source),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "values",
                    "annotations",
                    "contract-test-node",
                    "annotations",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-agreement",
            node_type_id=(
                "structure_annotation.secondary_structure_agreement"
            ),
            node_type_version="5.0.0",
            binding_id=(
                "structure_annotation.secondary_structure_agreement.direct"
            ),
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(
                candidate_source,
                value_source,
                residue_axis_resolver,
            ),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "candidates",
                    "subjects",
                    "resolve-axis",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "candidates",
                    "subjects",
                    "contract-test-node",
                    "subjects",
                ),
                WorkflowEdge(
                    "candidates",
                    "references",
                    "contract-test-node",
                    "references",
                ),
                WorkflowEdge(
                    "values",
                    "expected",
                    "contract-test-node",
                    "expected",
                ),
                WorkflowEdge(
                    "values",
                    "observed",
                    "contract-test-node",
                    "observed",
                ),
                WorkflowEdge(
                    "resolve-axis",
                    "residue_axes",
                    "contract-test-node",
                    "subject_residue_axes",
                ),
            ),
            expected_observation_counts={"scores": 1},
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-apply-secondary-to-prompt",
            node_type_id=(
                "structure_annotation.apply_secondary_structure_to_prompt"
            ),
            node_type_version="5.0.0",
            binding_id=(
                "structure_annotation."
                "apply_secondary_structure_to_prompt.direct"
            ),
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(candidate_source, value_source),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "values",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
                WorkflowEdge(
                    "values",
                    "expected",
                    "contract-test-node",
                    "secondary_structure_track",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-apply-sasa-to-prompt",
            node_type_id="structure_annotation.apply_sasa_to_prompt",
            node_type_version="5.0.0",
            binding_id="structure_annotation.apply_sasa_to_prompt.direct",
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(candidate_source, value_source),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "values",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
                WorkflowEdge(
                    "values",
                    "sasa_track",
                    "contract-test-node",
                    "sasa_track",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-expected-secondary-from-prompt",
            node_type_id=(
                "structure_annotation.expected_secondary_structure_from_prompt"
            ),
            node_type_version="5.0.0",
            binding_id=(
                "structure_annotation."
                "expected_secondary_structure_from_prompt.direct"
            ),
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(candidate_source, value_source),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "values",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
                WorkflowEdge(
                    "candidates",
                    "references",
                    "contract-test-node",
                    "references",
                ),
            ),
        ),
    )
    layout = ResidueLayout(
        chain_id="A",
        length=2,
        residue_ids=["A:1", "A:2"],
    )
    subject = _candidate_reference("fixture-structure-subject")
    port_cases = (
        ModulePackagePortCase(
            type_id="structure_annotation.dssp_annotations",
            version="4.0.0",
            valid_value=DSSPAnnotation(
                subject=subject,
                layout=layout,
                secondary_structure=("H", "C"),
                sasa=(10.0, None),
            ),
            invalid_values=(7,),
        ),
        ModulePackagePortCase(
            type_id="structure_annotation.secondary_structure_track",
            version="4.0.0",
            valid_value=StructureAnnotationTrack(
                subject=subject,
                layout=layout,
                values=("H", "_"),
            ),
            invalid_values=(7,),
        ),
        ModulePackagePortCase(
            type_id="structure_annotation.sasa_track",
            version="4.0.0",
            valid_value=StructureAnnotationTrack(
                subject=subject,
                layout=layout,
                values=(10.0, None),
            ),
            invalid_values=(7,),
        ),
    )

    report = verify_module_package_contract(
        STRUCTURE_ANNOTATION_PACKAGE,
        execution_cases=cases,
        port_cases=port_cases,
        supporting_registrations=(SOURCE_PACKAGE, *_prompt_authoring_packages()),
        work_root=tmp_path / "ctk",
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]


def test_agreement_emits_one_exact_subject_metric_method_observation(
    tmp_path: Path,
) -> None:
    from tests.fixtures.structure_annotation_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            STRUCTURE_ANNOTATION_PACKAGE,
            SOURCE_PACKAGE,
            *_prompt_authoring_packages(),
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("structure annotation agreement")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="candidates",
                node_type_id=(
                    "contract_test.structure_annotation_candidate_source"
                ),
                node_type_version="3.0.0",
                binding_id=(
                    "contract_test."
                    "structure_annotation_candidate_source.direct"
                ),
                binding_version="3.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="values",
                node_type_id=(
                    "contract_test.structure_annotation_value_source"
                ),
                node_type_version="3.0.0",
                binding_id=(
                    "contract_test.structure_annotation_value_source.direct"
                ),
                binding_version="3.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="resolve-axis",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                node_type_version="5.0.0",
                binding_id=(
                    "structure_transform."
                    "resolve_candidate_residue_axes.direct"
                ),
                binding_version="5.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="agreement",
                node_type_id=(
                    "structure_annotation.secondary_structure_agreement"
                ),
                node_type_version="5.0.0",
                binding_id=(
                    "structure_annotation."
                    "secondary_structure_agreement.direct"
                ),
                binding_version="5.0.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("candidates", "subjects", "values", "subjects"),
            WorkflowEdge("candidates", "references", "values", "references"),
            WorkflowEdge(
                "candidates",
                "subjects",
                "resolve-axis",
                "structure_candidates",
            ),
            WorkflowEdge("candidates", "subjects", "agreement", "subjects"),
            WorkflowEdge(
                "candidates",
                "references",
                "agreement",
                "references",
            ),
            WorkflowEdge("values", "expected", "agreement", "expected"),
            WorkflowEdge("values", "observed", "agreement", "observed"),
            WorkflowEdge(
                "resolve-axis",
                "residue_axes",
                "agreement",
                "subject_residue_axes",
            ),
        ),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )
    authoring.require_compiled(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration({}),
    )
    receipt = service.start(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id="structure-annotation-agreement",
    )
    projection = service.projection(project.id, receipt["run_id"])
    service.shutdown()

    subject_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "candidates"
        and output["output_port"] == "subjects"
    )
    reference_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "candidates"
        and output["output_port"] == "references"
    )
    axis_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "resolve-axis"
        and output["output_port"] == "residue_axes"
    )
    score_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "agreement"
    )
    subjects = _decode_output(catalog, service, projection, subject_output)
    references = _decode_output(
        catalog,
        service,
        projection,
        reference_output,
    )
    axis_association = _decode_output(
        catalog,
        service,
        projection,
        axis_output,
    ).entries[0]
    scores = _decode_output(catalog, service, projection, score_output)
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    subject = subjects.items[0]
    reference = references.items[0]
    structure_digest = catalog.require_port_type(
        "protein.structure",
        "4.0.0",
    ).content_digest(subject.data)
    subject_reference = CandidateDataReference(
        candidate_id=subject.candidate_id,
        data_type_id=subjects.item_type,
        content_digest=structure_digest,
    )
    reference_reference = CandidateDataReference(
        candidate_id=reference.candidate_id,
        data_type_id=references.item_type,
        content_digest=structure_digest,
    )
    assert observation.subject == subject_reference
    assert axis_association.subject == subject_reference
    assert observation.residue_axis is not None
    assert observation.residue_axis.axis_kind == "resolved_structure"
    assert observation.residue_axis.axis_contract.contract_id == (
        "structure_transform.resolved_residue_axis"
    )
    assert observation.residue_axis.axis_contract.contract_version == "4.0.0"
    assert observation.residue_axis.axis_content_digest == (
        catalog.require_port_type(
            "structure_transform.resolved_residue_axis",
            "4.0.0",
        ).content_digest(axis_association.residue_axis)
    )
    assert observation.residue_axis.source == subject_reference
    assert observation.residue_axis.layout == axis_association.residue_axis.layout
    assert observation.metric.contract_id == (
        "structure_annotation.secondary_structure_agreement"
    )
    assert observation.method.contract_id == (
        "structure_annotation.secondary_structure_agreement.method"
    )
    assert observation.context.to_public() == {
        "kind": "pairwise",
        "subject": {
            "role": "subject",
            "candidate": subject_reference.to_public(),
        },
        "reference": {
            "role": "reference",
            "candidate": reference_reference.to_public(),
        },
        "pairing_mode": "fixed_reference",
        "normalization": "exact-SS8-present-residue",
    }
    assert observation.value == 0.5
