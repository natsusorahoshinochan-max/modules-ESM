"""Public v2 contracts for reproducible structure comparison."""

from __future__ import annotations

from dataclasses import replace
import math

import pytest

from core import build_discovered_frozen_catalog, discover_module_packages
from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ModulePackagePortCase,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.port_types import PortValueError
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    CandidateCollection,
    ExactContractReference,
    PairwiseCandidateMapping,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
)
from modules.structure_comparison import (
    AlignmentAtomCorrespondence,
    StructureAlignmentEvidence,
    StructureAlignmentEvidenceCollection,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
)
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from tests.fixtures.structure_comparison_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


VERSION = "2.0.0"
SUBJECT_DIGEST = "sha256:" + "1" * 64
REFERENCE_DIGEST = "sha256:" + "2" * 64
METHOD_DIGEST = build_frozen_catalog(
    (STRUCTURE_COMPARISON_PACKAGE,)
).require_contract(
    "method",
    "structure_comparison.ca_sequence_svd.method",
    VERSION,
).contract_digest


def _alignment() -> StructureAlignmentEvidence:
    return StructureAlignmentEvidence(
        schema_version=VERSION,
        subject=PairwiseParticipant(
            role="subject",
            candidate_id="subject-1",
            content_digest=SUBJECT_DIGEST,
        ),
        reference=PairwiseParticipant(
            role="reference",
            candidate_id="reference-1",
            content_digest=REFERENCE_DIGEST,
        ),
        correspondence=(
            AlignmentAtomCorrespondence(
                subject_residue_id="A:1",
                subject_atom_name="CA",
                subject_coordinate=(1.0, 0.0, 0.0),
                reference_residue_id="R:9",
                reference_atom_name="CA",
                reference_coordinate=(0.0, 0.0, 0.0),
                transformed_subject_coordinate=(0.0, 0.0, 0.0),
                residual_distance=0.0,
            ),
            AlignmentAtomCorrespondence(
                subject_residue_id="A:2",
                subject_atom_name="CA",
                subject_coordinate=(2.0, 0.0, 0.0),
                reference_residue_id="R:10",
                reference_atom_name="CA",
                reference_coordinate=(1.0, 0.0, 0.0),
                transformed_subject_coordinate=(1.0, 0.0, 0.0),
                residual_distance=0.0,
            ),
        ),
        transform=StructureAlignmentTransform(
            maps_from_role="subject",
            maps_to_role="reference",
            row_vector_rotation=(
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            translation=(-1.0, 0.0, 0.0),
        ),
        normalization=StructureAlignmentNormalization(
            atom_selection="CA",
            subject_residue_count=2,
            reference_residue_count=2,
            aligned_atom_count=2,
            coverage_denominator="max(subject_residue_count,reference_residue_count)",
        ),
        rmsd=0.0,
        coverage=1.0,
        method=ExactContractReference(
            contract_kind="method",
            contract_id="structure_comparison.ca_sequence_svd.method",
            contract_version=VERSION,
            contract_digest=METHOD_DIGEST,
        ),
    )


def test_structure_comparison_is_one_package_with_five_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["structure_comparison"]
    assert registration.package_module == "modules.structure_comparison"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/align_single.yaml",
        "definitions/align_pairwise.yaml",
        "definitions/rmsd.yaml",
        "definitions/tm_score.yaml",
        "definitions/batch_tm_score.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    assert {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "structure_comparison"
        in catalog.owners[(kind, contract_id, version)]
    } == {
        ("structure_comparison.align_single", VERSION),
        ("structure_comparison.align_pairwise", VERSION),
        ("structure_comparison.rmsd", VERSION),
        ("structure_comparison.tm_score", VERSION),
        ("structure_comparison.batch_tm_score", VERSION),
    }


def test_alignment_nominal_values_round_trip_exact_evidence() -> None:
    catalog = build_discovered_frozen_catalog()
    alignment_type = catalog.require_port_type(
        "structure_comparison.alignment",
        VERSION,
    )
    collection_type = catalog.require_port_type(
        "structure_comparison.alignment_collection",
        VERSION,
    )
    alignment = _alignment()

    assert alignment_type.decode(alignment_type.encode(alignment)) == alignment
    collection = StructureAlignmentEvidenceCollection(
        schema_version=VERSION,
        pairing_source="candidate.pairing@2.0.0",
        accepted_cardinality="one_to_one_complete",
        alignments=(alignment,),
    )
    assert (
        collection_type.decode(collection_type.encode(collection))
        == collection
    )


@pytest.mark.parametrize(
    "invalid",
    (
        replace(_alignment(), correspondence=()),
        replace(
            _alignment(),
            subject=replace(
                _alignment().subject,
                content_digest=REFERENCE_DIGEST,
            ),
            reference=replace(
                _alignment().reference,
                candidate_id="subject-1",
            ),
        ),
        replace(
            _alignment(),
            transform=replace(
                _alignment().transform,
                translation=(math.inf, 0.0, 0.0),
            ),
        ),
        replace(
            _alignment(),
            transform=replace(
                _alignment().transform,
                row_vector_rotation=(
                    (2.0, 0.0, 0.0),
                    (0.0, 1.0, 0.0),
                    (0.0, 0.0, 1.0),
                ),
            ),
        ),
        replace(
            _alignment(),
            correspondence=(
                replace(
                    _alignment().correspondence[0],
                    residual_distance=1.0,
                ),
                _alignment().correspondence[1],
            ),
        ),
        replace(_alignment(), rmsd=1.0),
        replace(_alignment(), coverage=0.5),
        replace(
            _alignment(),
            method=replace(
                _alignment().method,
                contract_digest="sha256:" + "3" * 64,
            ),
        ),
    ),
)
def test_alignment_nominal_value_rejects_incomplete_or_conflicting_evidence(
    invalid: StructureAlignmentEvidence,
) -> None:
    port_type = build_discovered_frozen_catalog().require_port_type(
        "structure_comparison.alignment",
        VERSION,
    )

    with pytest.raises(PortValueError):
        port_type.encode(invalid)


def _decode_output(catalog: object, output: dict[str, object]) -> object:
    reference = output["port_type"]
    assert isinstance(reference, dict)
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    values = output["values"]
    assert isinstance(values, list) and len(values) == 1
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": port_type.type_id,
                "port_type_version": port_type.version,
                "value": values[0],
            }
        )
    )


def _workflow(
    workflow_id: str,
    *,
    scenario: str,
    pairwise: bool,
) -> WorkflowDocument:
    alignment_operation = "align_pairwise" if pairwise else "align_single"
    rmsd_binding = (
        "per_subject_counterpart" if pairwise else "fixed_reference"
    )
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_comparison_source",
        node_type_version=VERSION,
        binding_id="contract_test.structure_comparison_source.direct",
        binding_version=VERSION,
        node_parameters={"scenario": scenario},
        binding_parameters={},
    )
    alignment = WorkflowNodeInstance(
        node_id="alignment",
        node_type_id=f"structure_comparison.{alignment_operation}",
        node_type_version=VERSION,
        binding_id=(
            f"structure_comparison.{alignment_operation}.direct"
        ),
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )
    rmsd = WorkflowNodeInstance(
        node_id="rmsd",
        node_type_id="structure_comparison.rmsd",
        node_type_version=VERSION,
        binding_id=f"structure_comparison.rmsd.{rmsd_binding}",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )
    edges = [
        WorkflowEdge("source", "subjects", "alignment", "subjects"),
        WorkflowEdge("source", "references", "alignment", "references"),
        WorkflowEdge("source", "subjects", "rmsd", "subjects"),
        WorkflowEdge("source", "references", "rmsd", "references"),
        WorkflowEdge(
            "alignment",
            "alignments" if pairwise else "alignment",
            "rmsd",
            "alignments" if pairwise else "alignment",
        ),
    ]
    if pairwise:
        edges.extend(
            (
                WorkflowEdge("source", "pairing", "alignment", "pairing"),
                WorkflowEdge("source", "pairing", "rmsd", "pairing"),
            )
        )
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=workflow_id,
        nodes=(source, alignment, rmsd),
        edges=tuple(edges),
        contract_lock=(),
    )


def _run_comparison(
    tmp_path: object,
    *,
    scenario: str,
    pairwise: bool,
    replay: bool = False,
) -> tuple[object, tuple[dict[str, object], ...], tuple[tuple[dict[str, object], ...], ...]]:
    catalog = build_frozen_catalog(
        (STRUCTURE_COMPARISON_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("structure comparison")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = _workflow(
        project.id,
        scenario=scenario,
        pairwise=pairwise,
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    binding_ids = {
        node.binding_id for node in workflow.nodes
    }
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (binding_id, VERSION): {
                    "values": {},
                    "safe_fingerprint": "provider-free",
                    "invalidation_token": "structure-comparison-v1",
                }
                for binding_id in binding_ids
            }
        ),
    )
    projections = []
    event_groups = []
    try:
        for index in range(2 if replay else 1):
            receipt = service.start(
                project.id,
                workflow_revision=relocked["workflow_revision"],
                compile_id=compiled.public_receipt()["compile_id"],
                client_request_id=f"structure-comparison-{index}",
            )
            projections.append(
                service.projection(project.id, receipt["run_id"])
            )
            event_groups.append(
                service.public_events(project.id, receipt["run_id"])
            )
    finally:
        service.shutdown()
    return catalog, tuple(projections), tuple(event_groups)


def _outputs_by_node(
    catalog: object,
    projection: dict[str, object],
) -> dict[tuple[str, str], object]:
    outputs = {}
    raw_outputs = projection["outputs"]
    assert isinstance(raw_outputs, list)
    for output in raw_outputs:
        outputs[(output["node_id"], output["output_port"])] = (
            _decode_output(catalog, output)
        )
    return outputs


def test_single_alignment_preserves_role_orientation_and_emits_typed_rmsd(
    tmp_path: object,
) -> None:
    catalog, (projection,), (events,) = _run_comparison(
        tmp_path,
        scenario="single",
        pairwise=False,
    )

    assert projection["status"] == "succeeded"
    outputs = _outputs_by_node(catalog, projection)
    subjects = outputs[("source", "subjects")]
    references = outputs[("source", "references")]
    alignment = outputs[("alignment", "alignment")]
    scores = outputs[("rmsd", "scores")]
    assert isinstance(subjects, CandidateCollection)
    assert isinstance(references, CandidateCollection)
    assert isinstance(alignment, StructureAlignmentEvidence)
    assert isinstance(scores, ScoreCollection)
    assert alignment.subject.candidate_id == subjects.items[0].candidate_id
    assert (
        alignment.subject.content_digest
        == subjects.items[0].metadata["content_digest"]
    )
    assert alignment.reference.candidate_id == references.items[0].candidate_id
    assert (
        alignment.reference.content_digest
        == references.items[0].metadata["content_digest"]
    )
    assert alignment.transform.maps_from_role == "subject"
    assert alignment.transform.maps_to_role == "reference"
    assert alignment.normalization.aligned_atom_count == 3
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)
    assert alignment.coverage == pytest.approx(1.0, abs=1e-12)
    assert alignment.method.contract_digest == (
        catalog.require_contract(
            "method",
            "structure_comparison.ca_sequence_svd.method",
            VERSION,
        ).contract_digest
    )
    assert [
        (item.subject_residue_id, item.reference_residue_id)
        for item in alignment.correspondence
    ] == [("A:1", "R:1"), ("A:2", "R:2"), ("A:3", "R:3")]
    assert all(
        item.residual_distance == pytest.approx(0.0, abs=1e-12)
        for item in alignment.correspondence
    )
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    assert isinstance(observation, ScoreObservation)
    assert observation.candidate_id == alignment.subject.candidate_id
    assert observation.metric.contract_id == "structure_comparison.rmsd"
    assert observation.method.contract_id == "structure_comparison.rmsd.method"
    assert observation.context.subject == alignment.subject
    assert observation.context.reference == alignment.reference
    assert observation.context.pairing_mode == "fixed_reference"
    assert observation.value == pytest.approx(0.0, abs=1e-12)

    alignment_attempt = next(
        event["event"]["node_attempt_id"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "alignment"
    )
    operation_ids = {
        event["event"]["operation_attempt_id"]
        for event in events
        if event["event"]["type"] == "operation_attempt_started"
        and event["event"]["node_attempt_id"] == alignment_attempt
    }
    assert len(operation_ids) == 1
    assert {
        event["event"]["operation_attempt_id"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["operation_attempt_id"] in operation_ids
    } == operation_ids


def test_high_ambiguity_alignment_records_true_nested_engine_invocation(
    tmp_path: object,
) -> None:
    import importlib.metadata

    catalog, (projection,), (events,) = _run_comparison(
        tmp_path,
        scenario="ambiguous",
        pairwise=False,
    )

    assert projection["status"] == "succeeded"
    alignment = _outputs_by_node(catalog, projection)[
        ("alignment", "alignment")
    ]
    assert isinstance(alignment, StructureAlignmentEvidence)
    assert alignment.normalization.aligned_atom_count >= 3
    alignment_attempt = next(
        event["event"]["node_attempt_id"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "alignment"
    )
    operation_id = next(
        event["event"]["operation_attempt_id"]
        for event in events
        if event["event"]["type"] == "operation_attempt_started"
        and event["event"]["node_attempt_id"] == alignment_attempt
    )
    invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["operation_attempt_id"] == operation_id
    ]
    assert [event["engine_role"] for event in invocations] == [
        "sequence_alignment",
        "correspondence_tiebreak",
        "rigid_superposition",
    ]
    parent, child, superposition = invocations
    assert "parent_invocation_id" not in parent
    assert child["parent_invocation_id"] == parent["invocation_id"]
    assert (
        superposition["parent_invocation_id"]
        == parent["invocation_id"]
    )
    assert child["engine_identity"] == (
        "tmtools.tm_align/"
        f"{importlib.metadata.version('tmtools')}"
    )
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {
            parent["invocation_id"],
            child["invocation_id"],
            superposition["invocation_id"],
        }
    ]
    assert len(terminals) == 3
    assert {event["status"] for event in terminals} == {"succeeded"}


def test_pairwise_alignment_uses_exact_mapping_not_collection_order(
    tmp_path: object,
) -> None:
    catalog, (projection,), _ = _run_comparison(
        tmp_path,
        scenario="paired",
        pairwise=True,
    )

    assert projection["status"] == "succeeded"
    outputs = _outputs_by_node(catalog, projection)
    subjects = outputs[("source", "subjects")]
    references = outputs[("source", "references")]
    pairing = outputs[("source", "pairing")]
    alignments = outputs[("alignment", "alignments")]
    scores = outputs[("rmsd", "scores")]
    assert isinstance(subjects, CandidateCollection)
    assert isinstance(references, CandidateCollection)
    assert isinstance(pairing, PairwiseCandidateMapping)
    assert isinstance(alignments, StructureAlignmentEvidenceCollection)
    assert isinstance(scores, ScoreCollection)
    assert len(alignments.alignments) == 2
    assert [
        (
            alignment.subject.candidate_id,
            alignment.reference.candidate_id,
        )
        for alignment in alignments.alignments
    ] == [
        (
            entry.subject_candidate_id,
            entry.reference_candidate_id,
        )
        for entry in pairing.entries
    ]
    assert pairing.entries[0].reference_candidate_id == (
        references.items[0].candidate_id
    )
    assert pairing.entries[1].reference_candidate_id == (
        references.items[1].candidate_id
    )
    assert pairing.entries[0].subject_candidate_id == subjects.items[1].candidate_id
    assert pairing.entries[1].subject_candidate_id == subjects.items[0].candidate_id
    assert {
        (
            observation.context.subject.candidate_id,
            observation.context.reference.candidate_id,
        )
        for observation in scores.entries
    } == {
        (
            entry.subject_candidate_id,
            entry.reference_candidate_id,
        )
        for entry in pairing.entries
    }


def test_rmsd_contract_has_no_mutable_candidate_identity_parameter() -> None:
    catalog = build_discovered_frozen_catalog()
    node = catalog.require_contract(
        "node_type",
        "structure_comparison.rmsd",
        VERSION,
    )
    fixed = catalog.require_contract(
        "binding",
        "structure_comparison.rmsd.fixed_reference",
        VERSION,
    )
    paired = catalog.require_contract(
        "binding",
        "structure_comparison.rmsd.per_subject_counterpart",
        VERSION,
    )

    assert node.descriptor["node_parameters"] == {}
    assert fixed.descriptor["binding_parameters"] == {}
    assert paired.descriptor["binding_parameters"] == {}
    assert "candidate_id" not in node.descriptor_bytes.decode("utf-8")
    assert fixed.descriptor["produced_observations"][0][
        "context_profile"
    ]["pairing_mode"] == "fixed_reference"
    assert paired.descriptor["produced_observations"][0][
        "pairing_port"
    ] == "pairing"


def _source_node(scenario: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_comparison_source",
        node_type_version=VERSION,
        binding_id="contract_test.structure_comparison_source.direct",
        binding_version=VERSION,
        node_parameters={"scenario": scenario},
        binding_parameters={},
    )


def _alignment_node(
    pairwise: bool,
    *,
    fixed_reference: bool = False,
) -> WorkflowNodeInstance:
    operation = "align_pairwise" if pairwise else "align_single"
    binding_suffix = (
        "fixed_reference"
        if pairwise and fixed_reference
        else "direct"
    )
    return WorkflowNodeInstance(
        node_id="alignment-source",
        node_type_id=f"structure_comparison.{operation}",
        node_type_version=VERSION,
        binding_id=f"structure_comparison.{operation}.{binding_suffix}",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )


def test_structure_comparison_passes_ctk_for_all_nodes_and_bindings(
    tmp_path: object,
) -> None:
    single_source = _source_node("single")
    paired_source = _source_node("paired")
    fixed_source = _source_node("fixed_batch")
    single_alignment = _alignment_node(False)
    paired_alignment = _alignment_node(True)
    fixed_alignment = _alignment_node(True, fixed_reference=True)
    source_to_single = (
        WorkflowEdge("source", "subjects", "contract-test-node", "subjects"),
        WorkflowEdge(
            "source",
            "references",
            "contract-test-node",
            "references",
        ),
    )
    source_to_paired = (
        *source_to_single,
        WorkflowEdge("source", "pairing", "contract-test-node", "pairing"),
    )
    source_to_fixed = source_to_single
    cases = (
        ModulePackageContractCase(
            case_id="structure-comparison-align-single",
            node_type_id="structure_comparison.align_single",
            node_type_version=VERSION,
            binding_id="structure_comparison.align_single.direct",
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(single_source,),
            workflow_edges=source_to_single,
        ),
        ModulePackageContractCase(
            case_id="structure-comparison-align-pairwise",
            node_type_id="structure_comparison.align_pairwise",
            node_type_version=VERSION,
            binding_id="structure_comparison.align_pairwise.direct",
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(paired_source,),
            workflow_edges=source_to_paired,
        ),
        ModulePackageContractCase(
            case_id="structure-comparison-align-fixed-reference",
            node_type_id="structure_comparison.align_pairwise",
            node_type_version=VERSION,
            binding_id=(
                "structure_comparison.align_pairwise.fixed_reference"
            ),
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(fixed_source,),
            workflow_edges=source_to_fixed,
        ),
        ModulePackageContractCase(
            case_id="structure-comparison-rmsd-fixed",
            node_type_id="structure_comparison.rmsd",
            node_type_version=VERSION,
            binding_id="structure_comparison.rmsd.fixed_reference",
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(single_source, single_alignment),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "subjects",
                    "alignment-source",
                    "subjects",
                ),
                WorkflowEdge(
                    "source",
                    "references",
                    "alignment-source",
                    "references",
                ),
                WorkflowEdge(
                    "alignment-source",
                    "alignment",
                    "contract-test-node",
                    "alignment",
                ),
                *source_to_single,
            ),
            expected_observation_counts={"scores": 1},
        ),
        ModulePackageContractCase(
            case_id="structure-comparison-rmsd-paired",
            node_type_id="structure_comparison.rmsd",
            node_type_version=VERSION,
            binding_id=(
                "structure_comparison.rmsd.per_subject_counterpart"
            ),
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(paired_source, paired_alignment),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "subjects",
                    "alignment-source",
                    "subjects",
                ),
                WorkflowEdge(
                    "source",
                    "references",
                    "alignment-source",
                    "references",
                ),
                WorkflowEdge(
                    "source",
                    "pairing",
                    "alignment-source",
                    "pairing",
                ),
                WorkflowEdge(
                    "alignment-source",
                    "alignments",
                    "contract-test-node",
                    "alignments",
                ),
                *source_to_paired,
            ),
            expected_observation_counts={"scores": 2},
        ),
        ModulePackageContractCase(
            case_id="structure-comparison-tm-score-single",
            node_type_id="structure_comparison.tm_score",
            node_type_version=VERSION,
            binding_id="structure_comparison.tm_score.fixed_reference",
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(single_source, single_alignment),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "subjects",
                    "alignment-source",
                    "subjects",
                ),
                WorkflowEdge(
                    "source",
                    "references",
                    "alignment-source",
                    "references",
                ),
                WorkflowEdge(
                    "alignment-source",
                    "alignment",
                    "contract-test-node",
                    "alignment",
                ),
                *source_to_single,
            ),
            expected_observation_counts={"scores": 1},
        ),
        ModulePackageContractCase(
            case_id="structure-comparison-batch-tm-score-fixed",
            node_type_id="structure_comparison.batch_tm_score",
            node_type_version=VERSION,
            binding_id=(
                "structure_comparison.batch_tm_score.fixed_reference"
            ),
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(fixed_source, fixed_alignment),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "subjects",
                    "alignment-source",
                    "subjects",
                ),
                WorkflowEdge(
                    "source",
                    "references",
                    "alignment-source",
                    "references",
                ),
                WorkflowEdge(
                    "alignment-source",
                    "alignments",
                    "contract-test-node",
                    "alignments",
                ),
                *source_to_fixed,
            ),
            expected_observation_counts={"scores": 2},
        ),
        ModulePackageContractCase(
            case_id="structure-comparison-batch-tm-score-paired",
            node_type_id="structure_comparison.batch_tm_score",
            node_type_version=VERSION,
            binding_id=(
                "structure_comparison.batch_tm_score."
                "per_subject_counterpart"
            ),
            binding_version=VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="structure-comparison-ctk-v1",
            workflow_nodes=(paired_source, paired_alignment),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "subjects",
                    "alignment-source",
                    "subjects",
                ),
                WorkflowEdge(
                    "source",
                    "references",
                    "alignment-source",
                    "references",
                ),
                WorkflowEdge(
                    "source",
                    "pairing",
                    "alignment-source",
                    "pairing",
                ),
                WorkflowEdge(
                    "alignment-source",
                    "alignments",
                    "contract-test-node",
                    "alignments",
                ),
                *source_to_paired,
            ),
            expected_observation_counts={"scores": 2},
        ),
    )
    alignment = _alignment()
    collection = StructureAlignmentEvidenceCollection(
        schema_version=VERSION,
        pairing_source="candidate.pairing@2.0.0",
        accepted_cardinality="one_to_one_complete",
        alignments=(alignment,),
    )

    report = verify_module_package_contract(
        STRUCTURE_COMPARISON_PACKAGE,
        execution_cases=cases,
        port_cases=(
            ModulePackagePortCase(
                type_id="structure_comparison.alignment",
                version=VERSION,
                valid_value=alignment,
                invalid_values=(replace(alignment, correspondence=()),),
            ),
            ModulePackagePortCase(
                type_id="structure_comparison.alignment_collection",
                version=VERSION,
                valid_value=collection,
                invalid_values=(
                    replace(collection, alignments=()),
                ),
            ),
        ),
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert report.package_id == "structure_comparison"
    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert report.verified_port_types == (
        "structure_comparison.alignment@2.0.0",
        "structure_comparison.alignment_collection@2.0.0",
    )


def test_conflicting_pairing_fails_before_alignment_engine_or_cache_output(
    tmp_path: object,
) -> None:
    _, (projection,), (events,) = _run_comparison(
        tmp_path,
        scenario="conflicting_pairing",
        pairwise=True,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] in {"alignment", "rmsd"}
        for output in projection["outputs"]
    )
    alignment_attempt = next(
        event["event"]["node_attempt_id"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "alignment"
    )
    operation_id = next(
        event["event"]["operation_attempt_id"]
        for event in events
        if event["event"]["type"] == "operation_attempt_started"
        and event["event"]["node_attempt_id"] == alignment_attempt
    )
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        and event["event"]["operation_attempt_id"] == operation_id
        for event in events
    )


def test_structure_comparison_cache_replay_preserves_exact_evidence(
    tmp_path: object,
) -> None:
    catalog, projections, event_groups = _run_comparison(
        tmp_path,
        scenario="paired",
        pairwise=True,
        replay=True,
    )

    first, replayed = projections
    assert first["status"] == replayed["status"] == "succeeded"
    first_outputs = _outputs_by_node(catalog, first)
    replayed_outputs = _outputs_by_node(catalog, replayed)
    assert (
        first_outputs[("alignment", "alignments")]
        == replayed_outputs[("alignment", "alignments")]
    )
    assert (
        first_outputs[("rmsd", "scores")]
        == replayed_outputs[("rmsd", "scores")]
    )
    assert {
        item["resolution"] for item in replayed["node_dispositions"]
    } == {"cache_replayed"}
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        for event in event_groups[1]
    )


def test_pairwise_failure_publishes_no_partial_alignment_or_rmsd(
    tmp_path: object,
) -> None:
    _, (projection,), (events,) = _run_comparison(
        tmp_path,
        scenario="failing_pair",
        pairwise=True,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] in {"alignment", "rmsd"}
        for output in projection["outputs"]
    )
    alignment_attempt = next(
        event["event"]["node_attempt_id"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "alignment"
    )
    operation_id = next(
        event["event"]["operation_attempt_id"]
        for event in events
        if event["event"]["type"] == "operation_attempt_started"
        and event["event"]["node_attempt_id"] == alignment_attempt
    )
    invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["operation_attempt_id"] == operation_id
    ]
    assert [event["engine_role"] for event in invocations] == [
        "sequence_alignment",
        "bounded_correspondence_selection",
        "rigid_superposition",
    ]
    invocation_ids = {
        event["invocation_id"] for event in invocations
    }
    alignment_terminals = [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] in invocation_ids
    ]
    assert alignment_terminals == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
