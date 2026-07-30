"""Public v2 TM-score Observation contracts."""

from __future__ import annotations

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import ScoreCollection, ScoreObservation
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events
from tests.fixtures.structure_comparison_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


VERSION = "2.0.0"


def test_structure_comparison_declares_single_and_batch_tm_score_nodes() -> None:
    registration = {
        package.package_id: package
        for package in discover_module_packages()
    }["structure_comparison"]

    assert {
        resource.resource for resource in registration.node_definitions
    } >= {
        "definitions/tm_score.yaml",
        "definitions/batch_tm_score.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    assert catalog.require_contract(
        "node_type",
        "structure_comparison.tm_score",
        VERSION,
    )
    assert catalog.require_contract(
        "node_type",
        "structure_comparison.batch_tm_score",
        VERSION,
    )


def _single_tm_workflow(workflow_id: str) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=workflow_id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.structure_comparison_source",
                node_type_version=VERSION,
                binding_id="contract_test.structure_comparison_source.direct",
                binding_version=VERSION,
                node_parameters={"scenario": "single"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="alignment",
                node_type_id="structure_comparison.align_single",
                node_type_version=VERSION,
                binding_id="structure_comparison.align_single.direct",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="tm-score",
                node_type_id="structure_comparison.tm_score",
                node_type_version=VERSION,
                binding_id="structure_comparison.tm_score.fixed_reference",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "subjects", "alignment", "subjects"),
            WorkflowEdge("source", "references", "alignment", "references"),
            WorkflowEdge("alignment", "alignment", "tm-score", "alignment"),
            WorkflowEdge("source", "subjects", "tm-score", "subjects"),
            WorkflowEdge("source", "references", "tm-score", "references"),
        ),
        contract_lock=(),
    )


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


def test_single_tm_score_emits_exact_reference_normalized_observation(
    tmp_path: object,
) -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_COMPARISON_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("single TM-score")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=_single_tm_workflow(project.id),
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
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (node["binding_id"], VERSION): {
                    "values": {},
                    "safe_fingerprint": "provider-free",
                    "invalidation_token": "tm-score-v1",
                }
                for node in relocked["workflow"]["nodes"]
            }
        ),
    )
    try:
        receipt = service.start(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="single-tm-score",
        )
        wait_for_service_run_terminal_events(
            service,
            project.id,
            receipt["run_id"],
        )
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded"
    raw_score = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "tm-score"
        and output["output_port"] == "scores"
    )
    scores = _decode_output(catalog, raw_score)
    assert isinstance(scores, ScoreCollection)
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    assert isinstance(observation, ScoreObservation)
    assert observation.metric.contract_id == "structure_comparison.tm_score"
    assert observation.method.contract_id == (
        "structure_comparison.tm_score.reference_normalized.method"
    )
    assert observation.context.pairing_mode == "fixed_reference"
    assert observation.context.normalization == (
        "standard-reference-residue-count"
    )
    assert observation.context.evidence_content_digest.startswith("sha256:")
    assert observation.context.evidence_method.contract_id == (
        "structure_comparison.ca_sequence_svd.method"
    )
    assert observation.context.normalization_length == 3
    assert observation.context.aligned_atom_count == 3
    assert observation.value == 1.0
    tm_attempt = next(
        event["event"]["node_attempt_id"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "tm-score"
    )
    tm_operation = next(
        event["event"]["operation_attempt_id"]
        for event in events
        if event["event"]["type"] == "operation_attempt_started"
        and event["event"]["node_attempt_id"] == tm_attempt
    )
    invocation = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["operation_attempt_id"] == tm_operation
    )
    assert invocation["engine_role"] == "tm_score_optimization"
    assert invocation["engine_identity"].startswith("tmtools.tm_align/")


def _paired_batch_tm_workflow(workflow_id: str) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=workflow_id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.structure_comparison_source",
                node_type_version=VERSION,
                binding_id="contract_test.structure_comparison_source.direct",
                binding_version=VERSION,
                node_parameters={"scenario": "paired"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="alignment",
                node_type_id="structure_comparison.align_pairwise",
                node_type_version=VERSION,
                binding_id="structure_comparison.align_pairwise.direct",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="tm-score",
                node_type_id="structure_comparison.batch_tm_score",
                node_type_version=VERSION,
                binding_id=(
                    "structure_comparison.batch_tm_score."
                    "per_subject_counterpart"
                ),
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "subjects", "alignment", "subjects"),
            WorkflowEdge("source", "references", "alignment", "references"),
            WorkflowEdge("source", "pairing", "alignment", "pairing"),
            WorkflowEdge("alignment", "alignments", "tm-score", "alignments"),
            WorkflowEdge("source", "subjects", "tm-score", "subjects"),
            WorkflowEdge("source", "references", "tm-score", "references"),
            WorkflowEdge("source", "pairing", "tm-score", "pairing"),
        ),
        contract_lock=(),
    )


def test_batch_tm_score_uses_exact_pairing_not_collection_order(
    tmp_path: object,
) -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_COMPARISON_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("paired batch TM-score")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=_paired_batch_tm_workflow(project.id),
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
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (node["binding_id"], VERSION): {
                    "values": {},
                    "safe_fingerprint": "provider-free",
                    "invalidation_token": "tm-score-v1",
                }
                for node in relocked["workflow"]["nodes"]
            }
        ),
    )
    try:
        receipt = service.start(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="paired-batch-tm-score",
        )
        wait_for_service_run_terminal_events(
            service,
            project.id,
            receipt["run_id"],
        )
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded"
    outputs = {
        (output["node_id"], output["output_port"]): _decode_output(
            catalog,
            output,
        )
        for output in projection["outputs"]
    }
    pairing = outputs[("source", "pairing")]
    scores = outputs[("tm-score", "scores")]
    assert isinstance(scores, ScoreCollection)
    assert len(scores.entries) == 2
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
    assert {
        observation.source_partition for observation in scores.entries
    } == {"structure_comparison.tm_score.per_subject_counterpart"}
    assert {
        observation.context.pairing_mode for observation in scores.entries
    } == {"per_subject_counterpart"}
    assert all(
        observation.context.evidence_content_digest.startswith("sha256:")
        for observation in scores.entries
    )
    tm_attempt = next(
        event["event"]["node_attempt_id"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "tm-score"
    )
    tm_operation = next(
        event["event"]["operation_attempt_id"]
        for event in events
        if event["event"]["type"] == "operation_attempt_started"
        and event["event"]["node_attempt_id"] == tm_attempt
    )
    assert [
        event["event"]["engine_role"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["operation_attempt_id"] == tm_operation
    ] == ["tm_score_optimization", "tm_score_optimization"]


def _fixed_batch_tm_workflow(workflow_id: str) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=workflow_id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.structure_comparison_source",
                node_type_version=VERSION,
                binding_id="contract_test.structure_comparison_source.direct",
                binding_version=VERSION,
                node_parameters={"scenario": "fixed_batch"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="alignment",
                node_type_id="structure_comparison.align_pairwise",
                node_type_version=VERSION,
                binding_id=(
                    "structure_comparison.align_pairwise.fixed_reference"
                ),
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="tm-score",
                node_type_id="structure_comparison.batch_tm_score",
                node_type_version=VERSION,
                binding_id=(
                    "structure_comparison.batch_tm_score.fixed_reference"
                ),
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "subjects", "alignment", "subjects"),
            WorkflowEdge("source", "references", "alignment", "references"),
            WorkflowEdge("alignment", "alignments", "tm-score", "alignments"),
            WorkflowEdge("source", "subjects", "tm-score", "subjects"),
            WorkflowEdge("source", "references", "tm-score", "references"),
        ),
        contract_lock=(),
    )


def test_fixed_reference_batch_uses_one_exact_reference_for_every_subject(
    tmp_path: object,
) -> None:
    catalog = build_frozen_catalog(
        (STRUCTURE_COMPARISON_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("fixed-reference batch TM-score")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=_fixed_batch_tm_workflow(project.id),
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
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (node["binding_id"], VERSION): {
                    "values": {},
                    "safe_fingerprint": "provider-free",
                    "invalidation_token": "tm-score-v1",
                }
                for node in relocked["workflow"]["nodes"]
            }
        ),
    )
    try:
        receipt = service.start(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="fixed-batch-tm-score",
        )
        wait_for_service_run_terminal_events(
            service,
            project.id,
            receipt["run_id"],
        )
        projection = service.projection(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded"
    outputs = {
        (output["node_id"], output["output_port"]): _decode_output(
            catalog,
            output,
        )
        for output in projection["outputs"]
    }
    subjects = outputs[("source", "subjects")]
    references = outputs[("source", "references")]
    scores = outputs[("tm-score", "scores")]
    assert isinstance(scores, ScoreCollection)
    assert len(subjects.items) == len(scores.entries) == 2
    assert len(references.items) == 1
    expected_reference = references.items[0].candidate_id
    assert {
        observation.context.reference.candidate_id
        for observation in scores.entries
    } == {expected_reference}
    assert {
        observation.candidate_id for observation in scores.entries
    } == {candidate.candidate_id for candidate in subjects.items}
    assert {
        observation.source_partition for observation in scores.entries
    } == {"structure_comparison.tm_score.fixed_reference"}
    assert all(
        observation.context.normalization_length == 4
        and observation.context.aligned_atom_count == 3
        and observation.value == 0.75
        for observation in scores.entries
    )
