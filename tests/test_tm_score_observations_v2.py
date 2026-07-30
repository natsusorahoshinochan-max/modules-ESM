"""Public v2 TM-score Observation contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
from core.server import create_app
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    ExactContractReference,
    PairwiseObservationContext,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
)
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from protein_workbench_public import prepare_rest_request, validate_response
from tests.fixtures.public_v2 import (
    wait_for_service_run_terminal_events,
    wait_for_testclient_run_terminal,
)
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


def test_pairwise_evidence_provenance_is_closed_and_exact() -> None:
    participant = PairwiseParticipant(
        role="subject",
        candidate_id="subject",
        content_digest="sha256:" + "1" * 64,
    )
    reference = PairwiseParticipant(
        role="reference",
        candidate_id="reference",
        content_digest="sha256:" + "2" * 64,
    )
    method = ExactContractReference(
        contract_kind="method",
        contract_id="structure_comparison.ca_sequence_svd.method",
        contract_version=VERSION,
        contract_digest="sha256:" + "3" * 64,
    )

    with pytest.raises(ValueError, match="complete exact evidence provenance"):
        PairwiseObservationContext(
            subject=participant,
            reference=reference,
            pairing_mode="fixed_reference",
            normalization="standard-reference-residue-count",
            evidence_content_digest="not-a-digest",
            evidence_method=method,
            normalization_length=3,
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


def _execute_workflow(
    tmp_path: object,
    workflow: WorkflowDocument,
    *,
    replay: bool = False,
) -> tuple[
    object,
    tuple[dict[str, object], ...],
    tuple[tuple[dict[str, object], ...], ...],
]:
    catalog = build_frozen_catalog(
        (STRUCTURE_COMPARISON_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("TM-score contract")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=replace(workflow, workflow_id=project.id),
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
    projections = []
    event_groups = []
    try:
        for index in range(2 if replay else 1):
            receipt = service.start(
                project.id,
                workflow_revision=relocked["workflow_revision"],
                compile_id=compiled.public_receipt()["compile_id"],
                client_request_id=f"tm-score-contract-{index}",
            )
            wait_for_service_run_terminal_events(
                service,
                project.id,
                receipt["run_id"],
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


def test_single_tm_score_emits_exact_reference_normalized_observation(
    tmp_path: object,
) -> None:
    catalog, (projection,), (events,) = _execute_workflow(
        tmp_path,
        _single_tm_workflow("single-tm-score"),
    )

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


def test_nonfinite_tm_optimization_fails_before_score_publication(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NonfiniteOptimization:
        u = (
            (float("nan"), 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        )
        t = (0.0, 0.0, 0.0)

    monkeypatch.setattr(
        "modules.structure_comparison.implementation.tm_align",
        lambda *args: NonfiniteOptimization(),
    )
    _, (projection,), (events,) = _execute_workflow(
        tmp_path,
        _single_tm_workflow("nonfinite-tm-score"),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "tm-score"
        for output in projection["outputs"]
    )
    tm_attempt = next(
        event["event"]["node_attempt_id"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "tm-score"
    )
    assert any(
        event["event"]["type"] == "node_attempt_terminal"
        and event["event"]["node_attempt_id"] == tm_attempt
        and event["event"]["status"] == "failed"
        for event in events
    )


def test_tm_score_contracts_are_exact_and_publish_one_partition_per_binding() -> None:
    catalog = build_discovered_frozen_catalog()
    metric = catalog.require_contract(
        "metric",
        "structure_comparison.tm_score",
        VERSION,
    )
    method = catalog.require_contract(
        "method",
        "structure_comparison.tm_score.reference_normalized.method",
        VERSION,
    )
    assert metric.descriptor["canonical_range"] == {
        "minimum": 0,
        "maximum": 1,
    }
    assert metric.descriptor["direction"] == "higher_is_better"
    assert metric.descriptor["unit"] == "dimensionless"
    assert method.descriptor["algorithm_identity"]["formula"] == (
        "sum(1/(1+(distance/d0)^2))/reference_residue_count"
    )
    assert method.descriptor["source_identity"]["engine_api"] == (
        "tmtools.tm_align"
    )

    expected = {
        "structure_comparison.tm_score.fixed_reference": (
            "structure_comparison.tm_score.single",
            "fixed_reference",
            None,
        ),
        "structure_comparison.batch_tm_score.fixed_reference": (
            "structure_comparison.tm_score.fixed_reference",
            "fixed_reference",
            None,
        ),
        (
            "structure_comparison.batch_tm_score."
            "per_subject_counterpart"
        ): (
            "structure_comparison.tm_score.per_subject_counterpart",
            "per_subject_counterpart",
            "pairing",
        ),
    }
    for binding_id, (
        partition,
        pairing_mode,
        pairing_port,
    ) in expected.items():
        binding = catalog.require_contract("binding", binding_id, VERSION)
        assert binding.descriptor["binding_parameters"] == {}
        assert len(binding.descriptor["produced_observations"]) == 1
        declaration = binding.descriptor["produced_observations"][0]
        assert declaration["output_partition"] == partition
        assert declaration["guaranteed_multiplicity"] == "one"
        assert declaration["context_profile"] == {
            "kind": "pairwise",
            "subject_role": "subject",
            "reference_role": "reference",
            "pairing_mode": pairing_mode,
            "normalization": "standard-reference-residue-count",
        }
        assert declaration["pairing_port"] == pairing_port
        assert "score_id" not in binding.descriptor_bytes.decode("utf-8")


def test_tm_score_nodes_are_visible_through_the_public_catalog() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v2/catalog")

    assert response.status_code == 200
    payload = response.json()
    validate_response("catalog_snapshot", 200, payload)
    references = {
        (
            contract["reference"]["contract_kind"],
            contract["reference"]["contract_id"],
        )
        for contract in payload["contracts"]
    }
    assert {
        ("node_type", "structure_comparison.tm_score"),
        ("node_type", "structure_comparison.batch_tm_score"),
        ("metric", "structure_comparison.tm_score"),
        (
            "method",
            "structure_comparison.tm_score.reference_normalized.method",
        ),
    } <= references


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
    catalog, (projection,), (events,) = _execute_workflow(
        tmp_path,
        _paired_batch_tm_workflow("paired-batch-tm-score"),
    )

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


def test_batch_tm_score_executes_through_the_public_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    catalog = build_frozen_catalog(
        (STRUCTURE_COMPARISON_PACKAGE, SOURCE_PACKAGE)
    )
    workflow_bindings = {
        (
            "contract_test.structure_comparison_source.direct",
            VERSION,
        ),
        ("structure_comparison.align_pairwise.direct", VERSION),
        (
            "structure_comparison.batch_tm_score."
            "per_subject_counterpart",
            VERSION,
        ),
    }
    app = create_app(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            binding: {
                "values": {},
                "safe_fingerprint": "provider-free",
                "invalidation_token": "tm-score-public-v1",
            }
            for binding in workflow_bindings
        },
    )

    with TestClient(app) as client:
        def public_request(
            operation_id: str,
            request: dict[str, object],
            expected_status: int,
        ):
            prepared = prepare_rest_request(operation_id, request)
            response = client.request(
                prepared.method,
                prepared.route,
                json=prepared.json_body,
            )
            assert response.status_code == expected_status
            validate_response(
                operation_id,
                expected_status,
                response.json(),
            )
            return response.json()

        project_id = client.post(
            "/api/projects",
            json={"name": "paired TM-score public journey"},
        ).json()["id"]
        saved = public_request(
            "save_project_workflow",
            {
                "project_id": project_id,
                "expected_workflow_revision": 0,
                "workflow": _paired_batch_tm_workflow(
                    project_id
                ).to_public(),
            },
            200,
        )
        relocked = public_request(
            "relock_project_workflow",
            {
                "project_id": project_id,
                "workflow_revision": saved["workflow_revision"],
            },
            200,
        )
        compiled = public_request(
            "workflow_compile",
            {
                "project_id": project_id,
                "workflow_revision": relocked["workflow_revision"],
                "workflow": relocked["workflow"],
            },
            200,
        )
        started = public_request(
            "start_run",
            {
                "project_id": project_id,
                "workflow_revision": relocked["workflow_revision"],
                "compile_id": compiled["compile_id"],
                "client_request_id": "paired-tm-score-public",
            },
            202,
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started["run_id"],
        )

    assert projection["status"] == "succeeded"
    raw_scores = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "tm-score"
        and output["output_port"] == "scores"
    )
    scores = _decode_output(catalog, raw_scores)
    assert isinstance(scores, ScoreCollection)
    assert len(scores.entries) == 2
    assert {
        observation.source_partition
        for observation in scores.entries
    } == {"structure_comparison.tm_score.per_subject_counterpart"}


def test_batch_tm_score_cache_replay_preserves_observation_identities(
    tmp_path: object,
) -> None:
    catalog, projections, event_groups = _execute_workflow(
        tmp_path,
        _paired_batch_tm_workflow("paired-cache-replay"),
        replay=True,
    )
    first, replayed = projections

    assert first["status"] == replayed["status"] == "succeeded"
    score_outputs = []
    for projection in projections:
        raw_score = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "tm-score"
            and output["output_port"] == "scores"
        )
        score_outputs.append(_decode_output(catalog, raw_score))
    assert score_outputs[0] == score_outputs[1]
    assert [
        observation.identity
        for observation in score_outputs[0].entries
    ] == [
        observation.identity
        for observation in score_outputs[1].entries
    ]
    assert {
        disposition["resolution"]
        for disposition in replayed["node_dispositions"]
    } == {"cache_replayed"}
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        for event in event_groups[1]
    )


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
    catalog, (projection,), _ = _execute_workflow(
        tmp_path,
        _fixed_batch_tm_workflow("fixed-batch-tm-score"),
    )

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


def _mismatched_fixed_sources_workflow(workflow_id: str) -> WorkflowDocument:
    source_nodes = tuple(
        WorkflowNodeInstance(
            node_id=f"source-{suffix}",
            node_type_id="contract_test.structure_comparison_source",
            node_type_version=VERSION,
            binding_id="contract_test.structure_comparison_source.direct",
            binding_version=VERSION,
            node_parameters={
                "scenario": (
                    "fixed_batch" if suffix == "alignment" else "single"
                )
            },
            binding_parameters={},
        )
        for suffix in ("alignment", "score")
    )
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=workflow_id,
        nodes=(
            *source_nodes,
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
            WorkflowEdge(
                "source-alignment",
                "subjects",
                "alignment",
                "subjects",
            ),
            WorkflowEdge(
                "source-alignment",
                "references",
                "alignment",
                "references",
            ),
            WorkflowEdge("alignment", "alignments", "tm-score", "alignments"),
            WorkflowEdge(
                "source-score",
                "subjects",
                "tm-score",
                "subjects",
            ),
            WorkflowEdge(
                "source-score",
                "references",
                "tm-score",
                "references",
            ),
        ),
        contract_lock=(),
    )


def test_missing_exact_reference_fails_before_tm_score_engine(
    tmp_path: object,
) -> None:
    _, (projection,), (events,) = _execute_workflow(
        tmp_path,
        _mismatched_fixed_sources_workflow("mismatched-fixed-sources"),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "tm-score"
        for output in projection["outputs"]
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
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        and event["event"]["operation_attempt_id"] == tm_operation
        for event in events
    )
