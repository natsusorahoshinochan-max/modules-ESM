"""Public v2 contracts for the cohesive structure-annotation package."""

from __future__ import annotations

from core.catalog.authoring import AuthoringCapabilityProjection

from tests.support.ledger import public_run_events, public_run_projection

from protein_workbench_public.bootstrap import module_registrations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from core.catalog.port_contract import (
    _candidate_data_reference_to_canonical,
    observation_context_canonical,
)

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.errors import PortValueError
from core.operation import (
    OperationCall,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.resources import RunResources
from core.execution.runtime import (
    V2RunError,
    V2RunService,
)
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
from core.catalog.canonical import canonical_json_bytes
from core.workflow.document import WorkflowEdge
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.prompt import ProteinPrompt
from datatypes.residue import (
    CandidateResidueTrack,
    ResidueLayout,
    ResidueTrack,
)
from datatypes.structure import ProteinStructure
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from modules.structure_annotation.implementation import (
    DSSPComputeOperation,
    ExpectedSecondaryStructureFromPromptOperation,
    ObservedToConditioningOperation,
    SecondaryStructureAgreementOperation,
)
from modules.structure_annotation.adapter import (
    MKDSSP_PROCESS_TIMEOUT_SECONDS,
)
from modules.structure_annotation.package import (
    MODULE_PACKAGE as STRUCTURE_ANNOTATION_PACKAGE,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.residue_axis import resolve_residue_axis
from modules.structure_transform.port_types import (
    RESOLVED_AXIS_PORT_TYPE,
)
from tests.fixtures.scientific_operation import (
    admitted_port_fixture,
    build_operation,
    operation_call,
)
from tests.fixtures.structure_transform_sources.package import _FIXTURES


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _operation_call(
    *,
    inputs,
    node_parameters,
    binding_parameters,
    candidate_data=None,
) -> OperationCall:
    references = {} if candidate_data is None else candidate_data
    return OperationCall(
        inputs={
            name: admitted_port_fixture(
                value,
                port_type_id=(
                    "candidate.collection"
                    if name
                    in {"structure_candidates", "subjects", "references"}
                    else name
                ),
                value_content_digests=("sha256:" + ("f" * 64),),
                candidate_data=references.get(name, ()),
                scientific_axes=(
                    tuple(
                        ResidueAxisReference(
                            axis_kind="resolved_structure",
                            axis_contract=ExactContractReference(
                                **RESOLVED_AXIS_PORT_TYPE.reference()
                            ),
                            axis_content_digest=(
                                RESOLVED_AXIS_PORT_TYPE.content_digest(
                                    entry.residue_axis
                                )
                            ),
                            source=entry.subject,
                            layout=entry.residue_axis.layout,
                        )
                        for entry in value.entries
                    )
                    if name in {"residue_axes", "subject_residue_axes"}
                    else ()
                ),
            )
            for name, value in inputs.items()
        },
        node_parameters=node_parameters,
        binding_parameters=binding_parameters,
        effective_randomness={},
    )


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
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_PACKAGE,
    )
    from modules.residue_data.package import (
        MODULE_PACKAGE as RESIDUE_DATA_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    return (PROMPT_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE, RESIDUE_DATA_PACKAGE)


def _agreement_operation(resources: _InvocationRecorder) -> Any:
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )
    return build_operation(
        catalog,
        "structure_annotation.secondary_structure_agreement.direct",
        resources,
    )


def test_structure_annotation_is_one_package_with_four_nodes() -> None:
    registration = next(
        registration
        for registration in module_registrations()
        if registration.package_id == "structure_annotation"
    )
    assert registration.package_module == "modules.structure_annotation"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/dssp_compute.yaml",
        "definitions/observed_to_conditioning.yaml",
        "definitions/secondary_structure_agreement.yaml",
        "definitions/expected_secondary_structure_from_prompt.yaml",
    }

    catalog = build_frozen_catalog(module_registrations())
    owned_nodes = {
        contract.contract_id
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
        and contract.contract_id.startswith("structure_annotation.")
    }
    assert owned_nodes == {
        "structure_annotation.dssp_compute",
        "structure_annotation.observed_to_conditioning",
        "structure_annotation.secondary_structure_agreement",
        "structure_annotation.expected_secondary_structure_from_prompt",
    }


def test_structure_annotation_publishes_its_scientific_contracts() -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )

    methods = {
        contract.contract_id
        for contract in catalog.contracts
        if contract.contract_kind == "method"
        and contract.contract_id.startswith("structure_annotation.")
    }
    assert methods == {
        "structure_annotation.dssp_compute.method",
        "structure_annotation.observed_to_conditioning.method",
        "structure_annotation.secondary_structure_agreement.method",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.method"
        ),
    }
    ports = {
        port_type.type_id
        for port_type in catalog.port_types
        if port_type.type_id.startswith("structure_annotation.")
    }
    assert ports == {
        "structure_annotation.secondary_structure.observed",
        "structure_annotation.sasa.observed",
    }
    agreement_metric = catalog.require_contract(
        "metric",
        "structure_annotation.secondary_structure_agreement",
    )
    assert agreement_metric.descriptor["aggregation_semantics"] == {
        "kind": "equal_weight_fraction",
        "source_metric": (
            "structure_annotation.secondary_structure.position_agreement"
        ),
        "included_values": (
            "residues_with_present_exact_SS8_on_both_tracks"
        ),
    }
    position_metric = catalog.require_contract(
        "metric",
        "structure_annotation.secondary_structure.position_agreement",
    )
    assert position_metric.descriptor["value_shape"] == "per_residue"
    bindings = {
        contract.contract_id: contract
        for contract in catalog.contracts
        if contract.contract_kind == "binding"
        and contract.contract_id.startswith("structure_annotation.")
    }
    assert set(bindings) == {
        "structure_annotation.dssp_compute.mkdssp_local",
        "structure_annotation.observed_to_conditioning.direct",
        "structure_annotation.secondary_structure_agreement.direct",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct"
        ),
    }


def test_annotation_ports_preserve_multichain_layout_missing_and_ss8() -> None:
    port_types = {
        port_type.type_id: port_type
        for port_type in STRUCTURE_ANNOTATION_PACKAGE.port_types
    }
    subject = _candidate_reference("subject-structure")
    layout = ResidueLayout(["A:4", "A:6", "B:1", "B:2"])
    secondary_type = port_types["structure_annotation.secondary_structure.observed"]
    sasa_type = port_types["structure_annotation.sasa.observed"]

    secondary_track = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, ("G", None, "C", "E")),
    )
    observed_sasa = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, (14.5, None, 0.0, 91.25)),
    )

    decoded_secondary = secondary_type.decode(
        secondary_type.encode(secondary_track)
    )
    assert decoded_secondary == secondary_track
    decoded_sasa = sasa_type.decode(sasa_type.encode(observed_sasa))
    assert decoded_sasa == observed_sasa
    assert all(
        value is None or type(value) is float
        for value in decoded_sasa.track.values
    )

    invalid_sasa_wire = json.loads(sasa_type.encode(observed_sasa))
    invalid_sasa_wire["value"]["fields"]["track"]["fields"]["values"][0] = (
        "14.5"
    )
    with pytest.raises(PortValueError, match="non-negative"):
        sasa_type.decode(canonical_json_bytes(invalid_sasa_wire))

    with pytest.raises(PortValueError, match="canonical SS8"):
        secondary_type.encode(
            CandidateResidueTrack(
                subject=subject,
                track=ResidueTrack(layout, ("H", "-", "E", "C")),
            )
        )

    wire = json.loads(secondary_type.encode(secondary_track))["value"]
    assert wire["fields"]["track"]["fields"]["values"][1] is None


def test_annotation_wire_requires_subject_and_subject_changes_content_identity(
) -> None:
    port_types = {
        port_type.type_id: port_type
        for port_type in STRUCTURE_ANNOTATION_PACKAGE.port_types
    }
    layout = ResidueLayout(["A:1"])
    secondary_type = port_types["structure_annotation.secondary_structure.observed"]
    first_subject = _candidate_reference("subject-1", digest_symbol="a")
    same_id_new_content = _candidate_reference(
        "subject-1",
        digest_symbol="b",
    )
    same_content_new_id = _candidate_reference(
        "subject-2",
        digest_symbol="a",
    )

    tracks = tuple(
        CandidateResidueTrack(
            subject=subject,
            track=ResidueTrack(layout, ("H",)),
        )
        for subject in (
            first_subject,
            same_id_new_content,
            same_content_new_id,
        )
    )

    assert len({secondary_type.content_digest(value) for value in tracks}) == 3
    assert secondary_type.decode(
        secondary_type.encode(tracks[0])
    ) == tracks[0]

    legacy_wire = json.loads(secondary_type.encode(tracks[0]))
    del legacy_wire["value"]["fields"]["subject"]
    with pytest.raises(PortValueError, match="fields do not match"):
        secondary_type.decode(canonical_json_bytes(legacy_wire))


def test_dssp_operation_crosses_one_canonical_only_adapter_interface() -> None:
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    subject = _candidate_reference("subject-structure")
    axis = resolve_residue_axis(structure)
    layout = ResidueLayout(["A:1"])
    associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=subject,
                residue_axis=axis,
            ),
        )
    )
    secondary_track = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, ("C",)),
    )
    observed_sasa = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, (10.0,)),
    )

    class RecordingAdapter:
        def __init__(self) -> None:
            self.calls: list[
                tuple[object, CandidateDataReference]
            ] = []

        def annotate(
            self,
            residue_axis: object,
            *,
            subject: CandidateDataReference,
        ) -> tuple[
            CandidateResidueTrack[str],
            CandidateResidueTrack[float],
        ]:
            self.calls.append((residue_axis, subject))
            return (secondary_track, observed_sasa)

    adapter = RecordingAdapter()
    operation = DSSPComputeOperation(adapter)
    candidates = CandidateCollection(
        collection_id="subject-structures",
        item_type="protein.structure",
        items=[Candidate(candidate_id=subject.candidate_id, data=structure)],
    )
    output = operation.execute(
        _operation_call(
            inputs={
                "structure_candidates": candidates,
                "residue_axes": associations,
            },
            node_parameters={},
            binding_parameters={},
            candidate_data={"structure_candidates": (subject,)},
        )
    )

    assert adapter.calls == [(axis, subject)]
    assert output == {
        "secondary_structure": secondary_track,
        "sasa": observed_sasa,
    }


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
        def annotate(
            self,
            residue_axis: object,
            *,
            subject: CandidateDataReference,
        ) -> tuple[
            CandidateResidueTrack[str],
            CandidateResidueTrack[float],
        ]:
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
            _operation_call(
                inputs={
                    "structure_candidates": candidates,
                    "residue_axes": wrong_associations,
                },
                node_parameters={},
                binding_parameters={},
                candidate_data={"structure_candidates": (subject,)},
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
    layout = axis.layout
    secondary_track = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, ("C", "C", "C")),
    )
    observed_sasa = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, (1.0, 2.0, 3.0)),
    )

    class RecordingAdapter:
        def __init__(self) -> None:
            self.axes: list[object] = []

        def annotate(
            self,
            residue_axis: object,
            *,
            subject: CandidateDataReference,
        ) -> tuple[
            CandidateResidueTrack[str],
            CandidateResidueTrack[float],
        ]:
            assert subject == secondary_track.subject
            self.axes.append(residue_axis)
            return (secondary_track, observed_sasa)

    adapter = RecordingAdapter()
    output = DSSPComputeOperation(adapter).execute(
        _operation_call(
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
            candidate_data={"structure_candidates": (subject,)},
        )
    )

    assert adapter.axes == [axis]
    assert axis.layout.residue_ids == ("A:1", "A:2", "A:3")
    assert axis.residue_names == ("ALA", "MET", "GLY")
    assert output == {
        "secondary_structure": secondary_track,
        "sasa": observed_sasa,
    }


def test_dssp_compute_produces_observed_secondary_and_sasa_preserving_subject(
) -> None:
    subject = _candidate_reference("subject-structure")
    layout = ResidueLayout(["A:1", "A:2"])
    secondary_track = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, ("H", "C")),
    )
    observed_sasa = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, (12.0, None)),
    )

    class RecordingAdapter:
        def annotate(
            self,
            residue_axis: object,
            *,
            subject: CandidateDataReference,
        ) -> tuple[
            CandidateResidueTrack[str],
            CandidateResidueTrack[float],
        ]:
            return (secondary_track, observed_sasa)

    associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=subject,
                residue_axis=resolve_residue_axis(
                    ProteinStructure(
                        "ATOM      1  CA  GLY A   1       "
                        "1.000   2.000   3.000  1.00 20.00           C  \n"
                        "ATOM      2  CA  ALA A   2       "
                        "2.000   3.000   4.000  1.00 20.00           C  \n"
                        "TER\nEND\n"
                    )
                ),
            ),
        )
    )
    candidates = CandidateCollection(
        collection_id="subject-structures",
        item_type="protein.structure",
        items=[
            Candidate(
                candidate_id=subject.candidate_id,
                data=ProteinStructure(
                    "ATOM      1  CA  GLY A   1       "
                    "1.000   2.000   3.000  1.00 20.00           C  \n"
                    "ATOM      2  CA  ALA A   2       "
                    "2.000   3.000   4.000  1.00 20.00           C  \n"
                    "TER\nEND\n"
                ),
            )
        ],
    )
    output = DSSPComputeOperation(RecordingAdapter()).execute(
        _operation_call(
            inputs={
                "structure_candidates": candidates,
                "residue_axes": associations,
            },
            node_parameters={},
            binding_parameters={},
            candidate_data={"structure_candidates": (subject,)},
        )
    )

    assert output["secondary_structure"].subject == subject
    assert output["secondary_structure"].track.values == ("H", "C")
    assert output["sasa"].subject == subject
    assert output["sasa"].track.values == (12.0, None)


def test_observed_to_conditioning_drops_subject_from_one_observed_track() -> None:
    resources = _InvocationRecorder()
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )
    subject = _candidate_reference("subject-structure")
    layout = ResidueLayout(["A:1", "A:2"])
    operation = build_operation(
        catalog,
        "structure_annotation.observed_to_conditioning.direct",
        resources,
    )
    call = operation_call(
        catalog=catalog,
        binding_id="structure_annotation.observed_to_conditioning.direct",
        inputs={
            "secondary_structure": CandidateResidueTrack(
                subject=subject,
                track=ResidueTrack(layout, ("H", "C")),
            ),
        },
        node_parameters={},
        binding_parameters={},
    )

    result = operation.execute(call)

    assert "secondary_structure" in result
    assert isinstance(result["secondary_structure"], ResidueTrack)
    assert result["secondary_structure"].layout == layout
    assert result["secondary_structure"].values == ("H", "C")
    assert resources.invocations == 1


def test_observed_to_conditioning_requires_exactly_one_observed_input() -> None:
    resources = _InvocationRecorder()
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )
    subject = _candidate_reference("subject-structure")
    layout = ResidueLayout(["A:1"])
    operation = build_operation(
        catalog,
        "structure_annotation.observed_to_conditioning.direct",
        resources,
    )

    with pytest.raises(ValueError, match="exactly one observed"):
        operation.execute(
            operation_call(
                catalog=catalog,
                binding_id=(
                    "structure_annotation.observed_to_conditioning.direct"
                ),
                inputs={},
                node_parameters={},
                binding_parameters={},
            )
        )
    with pytest.raises(ValueError, match="exactly one observed"):
        operation.execute(
            operation_call(
                catalog=catalog,
                binding_id=(
                    "structure_annotation.observed_to_conditioning.direct"
                ),
                inputs={
                    "secondary_structure": CandidateResidueTrack(
                        subject=subject,
                        track=ResidueTrack(layout, ("H",)),
                    ),
                    "sasa": CandidateResidueTrack(
                        subject=subject,
                        track=ResidueTrack(layout, (10.0,)),
                    ),
                },
                node_parameters={},
                binding_parameters={},
            )
        )
    assert resources.invocations == 0


def test_expected_secondary_structure_from_prompt_projects_prompt() -> None:
    resources = _InvocationRecorder()
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "ATOM      2  CA  ALA A   2       "
        "2.000   3.000   4.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    structure_port = catalog.require_port_type("protein.structure")
    reference = CandidateDataReference(
        candidate_id="reference-structure",
        data_type_id="protein.structure",
        content_digest=structure_port.content_digest(structure),
    )
    layout = ResidueLayout(["A:1", "A:2"])
    prompt = ProteinPrompt(
        layout=layout,
        sequence=("A", "C"),
        coordinates=(None, None),
        secondary_structure=("C", "H"),
    )
    operation = build_operation(
        catalog,
        "structure_annotation.expected_secondary_structure_from_prompt.direct",
        resources,
    )
    call = operation_call(
        catalog=catalog,
        binding_id=(
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct"
        ),
        inputs={
            "protein_prompt": prompt,
            "references": CandidateCollection(
                "references",
                "protein.structure",
                (Candidate(reference.candidate_id, structure),),
            ),
        },
        node_parameters={},
        binding_parameters={},
    )

    result = operation.execute(call)

    assert result["secondary_structure"].subject == reference
    assert result["secondary_structure"].track.values == ("C", "H")


def test_agreement_reuses_the_admitted_subject_axis_reference() -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, *_prompt_authoring_packages())
    )
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    structure_port = catalog.require_port_type("protein.structure")
    subject = CandidateDataReference(
        candidate_id="subject",
        data_type_id="protein.structure",
        content_digest=structure_port.content_digest(structure),
    )
    reference = CandidateDataReference(
        candidate_id="reference",
        data_type_id="protein.structure",
        content_digest=structure_port.content_digest(structure),
    )
    layout = ResidueLayout(["A:1"])
    binding_id = "structure_annotation.secondary_structure_agreement.direct"
    operation = build_operation(
        catalog,
        binding_id,
        _InvocationRecorder(),
    )
    call = operation_call(
        catalog=catalog,
        binding_id=binding_id,
        inputs={
            "subjects": CandidateCollection(
                "subjects",
                "protein.structure",
                (Candidate("subject", structure),),
            ),
            "references": CandidateCollection(
                "references",
                "protein.structure",
                (Candidate("reference", structure),),
            ),
            "expected": CandidateResidueTrack(
                subject=reference,
                track=ResidueTrack(layout, ("H",)),
            ),
            "observed": CandidateResidueTrack(
                subject=subject,
                track=ResidueTrack(layout, ("H",)),
            ),
            "subject_residue_axes": (
                CandidateResolvedResidueAxisAssociations(
                    entries=(
                        CandidateResolvedResidueAxisAssociation(
                            subject,
                            resolve_residue_axis(structure),
                        ),
                    )
                )
            ),
        },
        node_parameters={},
        binding_parameters={},
    )
    axis_port = call.inputs["subject_residue_axes"]
    trusted_axis = replace(
        axis_port.scientific_axes[0],
        axis_content_digest="sha256:" + "a" * 64,
    )
    call = replace(
        call,
        inputs={
            **call.inputs,
            "subject_residue_axes": replace(
                axis_port,
                values=(
                    replace(
                        axis_port.values[0],
                        scientific_axes=(trusted_axis,),
                    ),
                ),
            ),
        },
    )

    observation = operation.execute(call)["scores"].entries[0]

    assert observation.residue_axis == trusted_axis


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
    operation = _agreement_operation(resources)
    layout = ResidueLayout(["A:1"])
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
    call = _operation_call(
        inputs={
            "subjects": subjects,
            "references": references,
            "expected": CandidateResidueTrack(
                subject=(
                    mismatched_reference
                    if track_role == "expected"
                    else expected_reference
                ),
                track=ResidueTrack(layout, ("H",)),
            ),
            "observed": CandidateResidueTrack(
                subject=(
                    mismatched_reference
                    if track_role == "observed"
                    else subject_reference
                ),
                track=ResidueTrack(layout, ("H",)),
            ),
            "subject_residue_axes": subject_residue_axes,
        },
        node_parameters={},
        binding_parameters={},
        candidate_data={
            "subjects": (subject_reference,),
            "references": (expected_reference,),
        },
    )

    with pytest.raises(ValueError, match=f"{track_role} track subject"):
        operation.execute(call)
    assert resources.invocations == 0


def test_agreement_checks_layout_after_exact_participant_binding() -> None:
    resources = _InvocationRecorder()
    operation = _agreement_operation(resources)
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
        "expected": CandidateResidueTrack(
            subject=reference,
            track=ResidueTrack(ResidueLayout(["A:1"]), ("H",)),
        ),
        "observed": CandidateResidueTrack(
            subject=subject,
            track=ResidueTrack(ResidueLayout(["A:2"]), ("H",)),
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
            _operation_call(
                inputs=inputs,
                node_parameters={},
                binding_parameters={},
                candidate_data={
                    "subjects": (subject,),
                    "references": (reference,),
                },
            )
        )
    assert resources.invocations == 0


def test_agreement_requires_exact_subject_axis_join_before_engine() -> None:
    resources = _InvocationRecorder()
    operation = _agreement_operation(resources)
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
    layout = ResidueLayout(["A:1"])
    with pytest.raises(
        ValueError,
        match="one exact resolved residue-axis association",
    ):
        operation.execute(
            _operation_call(
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
                    "expected": CandidateResidueTrack(
                        subject=reference,
                        track=ResidueTrack(layout, ("H",)),
                    ),
                    "observed": CandidateResidueTrack(
                        subject=subject,
                        track=ResidueTrack(layout, ("H",)),
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
                candidate_data={
                    "subjects": (subject,),
                    "references": (reference,),
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
    )
    binding = catalog.require_contract(
        "binding",
        "structure_annotation.dssp_compute.mkdssp_local",
    )

    assert node.descriptor["node_parameters"] == {}
    assert binding.descriptor["binding_parameters"] == {}
    assert binding.descriptor["execution_route"] == "adapter"
    assert binding.descriptor["route_behavior"] == {
        "behavior_id": "structure_annotation.mkdssp_local/adapter",
        "parameters": {
            "axis_source": (
                "exact-candidate-associated-authoritative-"
                "resolved-residue-axis"
            ),
            "binary": "mkdssp",
            "provider_contract": "mkdssp",
            "request_format": "PDB-v3.3-fixed-columns",
            "residue_reconciliation": (
                "dssp-summary-label-pair-via-atom-site-auth-fields-"
                "to-authoritative-axis-exact-identity"
            ),
            "response_format": "mkdssp-mmCIF",
        },
    }
    method_reference = binding.descriptor["method"]
    assert method_reference == {
        "contract_kind": "method",
        "contract_id": "structure_annotation.dssp_compute.method",
    }
    prerequisites = binding.descriptor["readiness_declaration"][
        "prerequisites"
    ]
    assert prerequisites["binary"] == {
        "name": "mkdssp",
        "path_source": "trusted_environment_configuration",
    }
    assert binding.descriptor["availability_declaration"][
        "prerequisites"
    ] == {
        "binary_configuration": {
            "name": "mkdssp",
            "path_source": "trusted_environment_configuration",
        }
    }
    assert tuple(
        dict(field) for field in binding.descriptor["environment_fields"]
    ) == (
        {
            "name": "dssp_binary",
            "required": True,
            "value_category": "filesystem_path",
        },
    )


def test_only_dssp_compute_crosses_an_adapter_route() -> None:
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
        "structure_annotation.observed_to_conditioning.direct",
        "structure_annotation.secondary_structure_agreement.direct",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct"
        ),
    }
    assert bindings[
        "structure_annotation.dssp_compute.mkdssp_local"
    ].descriptor["execution_route"] == "adapter"
    for binding_id in (
        "structure_annotation.observed_to_conditioning.direct",
        "structure_annotation.secondary_structure_agreement.direct",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct"
        ),
    ):
        descriptor = bindings[binding_id].descriptor
        assert descriptor["execution_route"] == "direct"


def _fake_dssp_binary(
    path: Path,
    *,
    output: str | None,
    exit_code: int = 0,
) -> Path:
    binary = path / "mkdssp-fixture"
    output_command = (
        "printf '\\377'\n"
        if output is None
        else "cat <<'DSSP_OUTPUT'\n" + output + "DSSP_OUTPUT\n"
    )
    binary.write_text(
        "#!/bin/sh\n"
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
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...], str]:
    binary = _fake_dssp_binary(
        tmp_path,
        output=dssp_output,
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
                binding_id="protein_io.import_structure.direct",
                node_parameters={"project_input_ref": "structure-input"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="resolve-axis",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                binding_id=(
                    "structure_transform."
                    "resolve_candidate_residue_axes.direct"
                ),
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="annotate",
                node_type_id="structure_annotation.dssp_compute",
                binding_id="structure_annotation.dssp_compute.mkdssp_local",
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
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    authoring.require_verified_commit(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(
                catalog,
                {
                    "structure_annotation.dssp_compute.mkdssp_local": {
                        "dssp_binary": configured_binary or str(binary)
                    }
                },
            ),
            result_store(projects),
        ),
        result_store(projects),
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
    projection = public_run_projection(service, project.id, receipt["run_id"])
    events = public_run_events(service, project.id, receipt["run_id"])
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


def test_mkdssp_route_uses_the_exact_120_second_process_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_timeouts: list[float] = []
    run_process = RunResources.run_managed_local_process

    def record_timeout(self: RunResources, **kwargs: Any):
        observed_timeouts.append(kwargs["timeout_seconds"])
        return run_process(self, **kwargs)

    monkeypatch.setattr(
        RunResources,
        "run_managed_local_process",
        record_timeout,
    )
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
X 1 A 1 ?
#
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
fixture X 1 GLY . 10.0
#
""",
    )

    assert projection["status"] == "succeeded"
    assert MKDSSP_PROCESS_TIMEOUT_SECONDS == 120.0
    assert observed_timeouts == [120.0]


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
    ss_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
        and item["output_port"] == "secondary_structure"
    )
    sasa_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
        and item["output_port"] == "sasa"
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
    secondary = _decode_output(catalog, service, projection, ss_output)
    sasa = _decode_output(catalog, service, projection, sasa_output)
    assert secondary.subject == association.subject
    assert secondary.track.layout == association.residue_axis.layout
    assert secondary.track.layout.residue_ids == (
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
    assert secondary.track.values == (
        "G",
        "H",
        "I",
        "T",
        "E",
        "B",
        "S",
        "C",
        "C",
    )
    assert sasa.track.values == (
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
    ss_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
        and item["output_port"] == "secondary_structure"
    )
    sasa_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
        and item["output_port"] == "sasa"
    )
    secondary = _decode_output(catalog, service, projection, ss_output)
    sasa = _decode_output(catalog, service, projection, sasa_output)
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
    assert secondary.subject == association.subject
    assert secondary.track.layout == association.residue_axis.layout
    assert secondary.track.layout.residue_ids == ("A:1", "A:2", "A:3")
    assert association.residue_axis.residue_names == ("ALA", "MET", "GLY")
    assert secondary.track.values == ("H", "C", "E")
    assert sasa.track.values == (10.0, 20.0, 30.0)


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


def test_dssp_dot_and_p_convert_to_canonical_coil(
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
    ss_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
        and item["output_port"] == "secondary_structure"
    )
    secondary = _decode_output(catalog, service, projection, ss_output)
    assert secondary.track.values == ("C", "C")


def test_dssp_readiness_accepts_configured_executable_without_banner_gate(
    tmp_path: Path,
) -> None:
    from modules.structure_annotation.adapter import mkdssp_readiness

    binary = _fake_dssp_binary(
        tmp_path,
        output="unused\n",
    )

    assert mkdssp_readiness({"dssp_binary": binary}).passing is True


def test_unready_dssp_rejects_before_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, projection, events, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C  \n"
            "TER\nEND\n"
        ),
        dssp_output="unused\n",
        configured_binary=str(tmp_path / "missing-mkdssp"),
    )

    assert projection["status"] == "failed"
    failed_attempt_id = next(
        message["event"]["node_attempt_id"]
        for message in events
        if message["event"]["type"] == "node_attempt_started"
        and message["event"]["node_id"] == "annotate"
    )
    assert not any(
        message["event"]["type"] == "operation_attempt_started"
        and message["event"]["node_attempt_id"] == failed_attempt_id
        for message in events
    )
    failed_terminal = next(
        message["event"]
        for message in events
        if message["event"]["type"] == "node_attempt_terminal"
        and message["event"]["node_attempt_id"] == failed_attempt_id
    )
    assert failed_terminal["failure_origin"] == "binding"
    assert failed_terminal["error"]["code"] == "readiness_rejected"


def test_structure_annotation_passes_ctk_for_all_four_nodes(
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
        binding_id=(
            "contract_test.structure_annotation_candidate_source.direct"
        ),
        node_parameters={},
        binding_parameters={},
    )
    residue_axis_resolver = WorkflowNodeInstance(
        node_id="resolve-axis",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        node_parameters={},
        binding_parameters={},
    )
    value_source = WorkflowNodeInstance(
        node_id="values",
        node_type_id="contract_test.structure_annotation_value_source",
        binding_id="contract_test.structure_annotation_value_source.direct",
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
            binding_id="structure_annotation.dssp_compute.mkdssp_local",
            node_parameters={},
            binding_parameters={},
            environment_values={"dssp_binary": str(binary)},
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
            node_type_id="structure_annotation.observed_to_conditioning",
            binding_id="structure_annotation.observed_to_conditioning.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(candidate_source, value_source),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "values",
                    "annotations",
                    "contract-test-node",
                    "secondary_structure",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-sasa",
            node_type_id="structure_annotation.observed_to_conditioning",
            binding_id="structure_annotation.observed_to_conditioning.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(candidate_source, value_source),
            workflow_edges=value_source_edges + (
                WorkflowEdge(
                    "values",
                    "sasa",
                    "contract-test-node",
                    "sasa",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-agreement",
            node_type_id=(
                "structure_annotation.secondary_structure_agreement"
            ),
            binding_id=(
                "structure_annotation.secondary_structure_agreement.direct"
            ),
            node_parameters={},
            binding_parameters={},
            environment_values={},
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
            case_id="structure-annotation-expected-secondary-from-prompt",
            node_type_id=(
                "structure_annotation.expected_secondary_structure_from_prompt"
            ),
            binding_id=(
                "structure_annotation."
                "expected_secondary_structure_from_prompt.direct"
            ),
            node_parameters={},
            binding_parameters={},
            environment_values={},
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
    layout = ResidueLayout(["A:1", "A:2"])
    subject = _candidate_reference("fixture-structure-subject")
    port_cases = (
        ModulePackagePortCase(
            type_id="structure_annotation.secondary_structure.observed",
            valid_value=CandidateResidueTrack(
                subject=subject,
                track=ResidueTrack(layout, ("H", "C")),
            ),
            invalid_values=(7,),
        ),
        ModulePackagePortCase(
            type_id="structure_annotation.sasa.observed",
            valid_value=CandidateResidueTrack(
                subject=subject,
                track=ResidueTrack(layout, (10.0, None)),
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
                binding_id=(
                    "contract_test."
                    "structure_annotation_candidate_source.direct"
                ),
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="values",
                node_type_id=(
                    "contract_test.structure_annotation_value_source"
                ),
                binding_id=(
                    "contract_test.structure_annotation_value_source.direct"
                ),
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="resolve-axis",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                binding_id=(
                    "structure_transform."
                    "resolve_candidate_residue_axes.direct"
                ),
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="agreement",
                node_type_id=(
                    "structure_annotation.secondary_structure_agreement"
                ),
                binding_id=(
                    "structure_annotation."
                    "secondary_structure_agreement.direct"
                ),
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
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    authoring.require_verified_commit(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(catalog, {}),
            result_store(projects),
        ),
        result_store(projects),
    )
    receipt = service.start(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id="structure-annotation-agreement",
    )
    projection = public_run_projection(service, project.id, receipt["run_id"])
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
    assert observation.residue_axis.axis_content_digest == (
        catalog.require_port_type(
            "structure_transform.resolved_residue_axis",
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
    assert observation_context_canonical(observation.context) == {
        "kind": "pairwise",
        "subject": {
            "role": "subject",
            "candidate": _candidate_data_reference_to_canonical(subject_reference),
        },
        "reference": {
            "role": "reference",
            "candidate": _candidate_data_reference_to_canonical(
                reference_reference
            ),
        },
        "pairing_mode": "fixed_reference",
        "normalization": "exact-SS8-present-residue",
    }
