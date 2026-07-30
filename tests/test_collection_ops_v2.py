"""Public v2 contracts for partition-preserving collection operations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ProjectManager,
    SelectionInput,
    SelectionObjective,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowCompileError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    compile_workflow,
    build_discovered_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
    relock_workflow,
    verify_module_package_contract,
)
from core.port_types import PORT_VALUE_NAMESPACE, canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    Score,
    ScoreCollection,
    ScoreObservation,
)
from modules.collection_ops.implementation import CollectionOpsImplementation
from modules.collection_ops.package import MODULE_PACKAGE
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events


VERSION = "2.0.0"


def _source(partition: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=f"source-{partition}",
        node_type_id="contract_test.collection_ops_source",
        node_type_version=VERSION,
        binding_id=f"contract_test.collection_ops_source.{partition}",
        binding_version=VERSION,
        node_parameters={"candidate_count": 1},
        binding_parameters={},
    )


def test_collection_ops_is_one_package_with_two_exact_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["collection_ops"]
    assert registration is MODULE_PACKAGE
    assert registration.package_module == "modules.collection_ops"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/concat_candidates.yaml",
        "definitions/merge_scores.yaml",
    }
    assert len(registration.bindings) == 2
    assert len(registration.methods) == 2

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "collection_ops" in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("collection_ops.concat_candidates", VERSION),
        ("collection_ops.merge_scores", VERSION),
    }
    assert not any(
        "aggregate" in contract_id
        for contract_kind, contract_id, _ in catalog.owners
        if contract_kind == "node_type"
        and "collection_ops"
        in catalog.owners[(contract_kind, contract_id, VERSION)]
    )


def test_collection_ports_and_score_union_are_closed_and_versioned() -> None:
    catalog = build_discovered_frozen_catalog()
    candidates = catalog.require_contract(
        "node_type",
        "collection_ops.concat_candidates",
        VERSION,
    ).descriptor
    scores = catalog.require_contract(
        "node_type",
        "collection_ops.merge_scores",
        VERSION,
    ).descriptor
    score_binding = catalog.require_contract(
        "binding",
        "collection_ops.merge_scores.direct",
        VERSION,
    ).descriptor

    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["required"],
            port["multiplicity"],
        )
        for port in candidates["inputs"]
    ] == [
        ("candidates_a", "candidate.collection", False, "one"),
        ("candidates_b", "candidate.collection", False, "one"),
        ("candidates_c", "candidate.collection", False, "one"),
    ]
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["required"],
            port["multiplicity"],
        )
        for port in scores["inputs"]
    ] == [
        ("scores_a", "score.collection", False, "one"),
        ("scores_b", "score.collection", False, "one"),
        ("scores_c", "score.collection", False, "one"),
    ]
    assert score_binding["produced_observations"] == ()
    assert score_binding["observation_propagation"] == {
        "schema_version": VERSION,
        "mode": "union",
        "output_port": "scores",
        "input_ports": ("scores_a", "scores_b", "scores_c"),
        "filter": None,
        "absent_input_policy": "ignore",
    }


def test_both_nodes_pass_the_shared_contract_test_kit(
    tmp_path: Path,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source_a = _source("a")
    source_b = _source("b")
    candidate_case = ModulePackageContractCase(
        case_id="collection-ops-concat-candidates",
        node_type_id="collection_ops.concat_candidates",
        node_type_version=VERSION,
        binding_id="collection_ops.concat_candidates.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="provider-free",
        invalidation_token="collection-ops-candidates-v1",
        workflow_nodes=(source_a, source_b),
        workflow_edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "contract-test-node",
                "candidates_a",
            ),
            WorkflowEdge(
                "source-b",
                "candidates",
                "contract-test-node",
                "candidates_b",
            ),
        ),
        expected_candidate_counts={"candidates": 2},
    )
    score_case = ModulePackageContractCase(
        case_id="collection-ops-merge-scores",
        node_type_id="collection_ops.merge_scores",
        node_type_version=VERSION,
        binding_id="collection_ops.merge_scores.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="provider-free",
        invalidation_token="collection-ops-scores-v1",
        workflow_nodes=(source_a, source_b),
        workflow_edges=(
            WorkflowEdge(
                "source-a",
                "scores",
                "contract-test-node",
                "scores_a",
            ),
            WorkflowEdge(
                "source-b",
                "scores",
                "contract-test-node",
                "scores_b",
            ),
        ),
        expected_observation_counts={"scores": 2},
    )

    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=(candidate_case, score_case),
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
    ]


def _run_public_collection_workflow(
    tmp_path: Path,
    *,
    operation: str,
    counts: tuple[int, int] = (2, 1),
    connected_partitions: tuple[str, ...] = ("a", "b"),
) -> tuple[object, dict[str, object], dict[str, object], tuple[dict, ...]]:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"collection operations {operation}")
    port = "candidates" if operation == "concat_candidates" else "scores"
    target_port = (
        "candidates" if operation == "concat_candidates" else "scores"
    )
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source-a",
                node_type_id="contract_test.collection_ops_source",
                node_type_version=VERSION,
                binding_id="contract_test.collection_ops_source.a",
                binding_version=VERSION,
                node_parameters={"candidate_count": counts[0]},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="source-b",
                node_type_id="contract_test.collection_ops_source",
                node_type_version=VERSION,
                binding_id="contract_test.collection_ops_source.b",
                binding_version=VERSION,
                node_parameters={"candidate_count": counts[1]},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="collection-op",
                node_type_id=f"collection_ops.{operation}",
                node_type_version=VERSION,
                binding_id=f"collection_ops.{operation}.direct",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=tuple(
            WorkflowEdge(
                f"source-{partition}",
                port,
                "collection-op",
                f"{target_port}_{partition}",
            )
            for partition in connected_partitions
        ),
        contract_lock=(),
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    locked = parse_workflow_document(relocked["workflow"])
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=locked,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration({}),
    )

    def run(request_id: str) -> tuple[dict[str, object], tuple[dict, ...]]:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=request_id,
        )
        wait_for_service_run_terminal_events(
            service,
            project.id,
            receipt["run_id"],
        )
        return (
            service.projection(project.id, receipt["run_id"]),
            service.public_events(project.id, receipt["run_id"]),
        )

    first, _ = run("collection-ops-first")
    second, replay_events = run("collection-ops-second")
    service.shutdown()
    return catalog, first, second, replay_events


def _decoded_outputs(
    catalog: object,
    projection: dict[str, object],
) -> dict[tuple[str, str], object]:
    decoded: dict[tuple[str, str], object] = {}
    for output in projection["outputs"]:
        reference = output["port_type"]
        port_type = catalog.require_port_type(
            reference["contract_id"],
            reference["contract_version"],
        )
        decoded[(output["node_id"], output["output_port"])] = (
            port_type.decode(
                canonical_json_bytes(
                    {
                        "schema_namespace": PORT_VALUE_NAMESPACE,
                        "port_type_id": reference["contract_id"],
                        "port_type_version": reference[
                            "contract_version"
                        ],
                        "value": output["values"][0],
                    }
                )
            )
        )
    return decoded


def test_public_candidate_concatenation_preserves_exact_input_candidates(
    tmp_path: Path,
) -> None:
    catalog, first, second, replay_events = (
        _run_public_collection_workflow(
            tmp_path,
            operation="concat_candidates",
        )
    )
    assert first["status"] == second["status"] == "succeeded"
    first_values = _decoded_outputs(catalog, first)
    replay_values = _decoded_outputs(catalog, second)
    left = first_values[("source-a", "candidates")]
    right = first_values[("source-b", "candidates")]
    concatenated = first_values[("collection-op", "candidates")]

    assert concatenated.items == [*left.items, *right.items]
    assert [item.candidate_id for item in concatenated.items] == [
        *[item.candidate_id for item in left.items],
        *[item.candidate_id for item in right.items],
    ]
    assert concatenated.items[1].parent_ids == [
        concatenated.items[0].candidate_id
    ]
    assert [
        (
            item.metadata["producer_result_identity"],
            item.metadata["output_port"],
            item.metadata["sample_slot"],
            item.metadata["fixture_partition"],
        )
        for item in concatenated.items
    ] == [
        (
            item.metadata["producer_result_identity"],
            item.metadata["output_port"],
            item.metadata["sample_slot"],
            item.metadata["fixture_partition"],
        )
        for item in [*left.items, *right.items]
    ]
    assert replay_values[("collection-op", "candidates")] == concatenated
    assert all(
        disposition["resolution"] == "cache_replayed"
        for disposition in second["node_dispositions"]
    )
    assert not {
        "operation_attempt_started",
        "engine_invocation_started",
    }.intersection(
        event["event"]["type"] for event in replay_events
    )


def test_public_score_merge_preserves_observation_identity_and_partitions(
    tmp_path: Path,
) -> None:
    catalog, first, second, replay_events = (
        _run_public_collection_workflow(
            tmp_path,
            operation="merge_scores",
        )
    )
    assert first["status"] == second["status"] == "succeeded"
    first_values = _decoded_outputs(catalog, first)
    replay_values = _decoded_outputs(catalog, second)
    left = first_values[("source-a", "scores")]
    right = first_values[("source-b", "scores")]
    merged = first_values[("collection-op", "scores")]

    assert merged.entries == [*left.entries, *right.entries]
    assert [
        (
            entry.identity,
            entry.value,
            entry.source_partition,
            entry.candidate_id,
            entry.method,
            entry.context,
        )
        for entry in merged.entries
    ] == [
        (
            entry.identity,
            entry.value,
            entry.source_partition,
            entry.candidate_id,
            entry.method,
            entry.context,
        )
        for entry in [*left.entries, *right.entries]
    ]
    assert {
        entry.source_partition for entry in merged.entries
    } == {
        "contract_test.partition.a",
        "contract_test.partition.b",
    }
    assert replay_values[("collection-op", "scores")] == merged
    assert all(
        disposition["resolution"] == "cache_replayed"
        for disposition in second["node_dispositions"]
    )
    assert not {
        "operation_attempt_started",
        "engine_invocation_started",
    }.intersection(
        event["event"]["type"] for event in replay_events
    )


def test_public_optional_score_inputs_distinguish_empty_from_absent(
    tmp_path: Path,
) -> None:
    catalog, empty_first, empty_replay, _ = (
        _run_public_collection_workflow(
            tmp_path / "empty",
            operation="merge_scores",
            counts=(0, 1),
            connected_partitions=("a",),
        )
    )
    assert empty_first["status"] == empty_replay["status"] == "succeeded"
    assert (
        _decoded_outputs(
            catalog,
            empty_first,
        )[("collection-op", "scores")].entries
        == []
    )

    _, absent_first, absent_replay, _ = (
        _run_public_collection_workflow(
            tmp_path / "absent",
            operation="merge_scores",
            connected_partitions=(),
        )
    )
    assert absent_first["status"] == absent_replay["status"] == "failed"
    assert not any(
        output["node_id"] == "collection-op"
        for output in absent_first["outputs"]
    )


def _observation(
    *,
    value: object = 0.25,
    source_partition: str = "partition-a",
) -> ScoreObservation:
    digest = "sha256:" + "1" * 64
    return ScoreObservation(
        candidate_id="candidate-a",
        metric=ExactContractReference(
            "metric",
            "contract_test.metric",
            VERSION,
            digest,
        ),
        method=ExactContractReference(
            "method",
            "contract_test.method",
            VERSION,
            digest,
        ),
        context=IntrinsicObservationContext(),
        value=value,
        source_partition=source_partition,
    )


def test_candidate_inputs_are_normalized_without_replacement_or_ambiguity() -> None:
    implementation = CollectionOpsImplementation("concat_candidates")
    first = Candidate(
        "candidate-a",
        ProteinSequence("ACD"),
        parent_ids=["parent-a"],
        metadata={
            "producer_result_identity": "sha256:" + "2" * 64,
            "output_port": "candidates",
            "sample_slot": "0:0",
        },
    )
    second = Candidate(
        "candidate-b",
        ProteinSequence("ACE"),
        parent_ids=["parent-b"],
        metadata={
            "producer_result_identity": "sha256:" + "3" * 64,
            "output_port": "candidates",
            "sample_slot": "0:0",
        },
    )
    empty = CandidateCollection("empty", "protein.sequence", [])
    left = CandidateCollection("left", "protein.sequence", [first])
    right = CandidateCollection("right", "protein.sequence", [second])

    output = implementation.execute(
        inputs={
            "candidates_c": empty,
            "candidates_b": right,
            "candidates_a": left,
        },
        node_parameters={},
        binding_parameters={},
    )["candidates"]

    assert output.items == [first, second]
    assert output.items[0] is first
    assert output.items[1] is second
    assert first.parent_ids == ["parent-a"]
    assert first.metadata["sample_slot"] == "0:0"
    assert implementation.execute(
        inputs={"candidates_b": empty},
        node_parameters={},
        binding_parameters={},
    )["candidates"].items == []
    with pytest.raises(ValueError, match="at least one connected"):
        implementation.execute(
            inputs={},
            node_parameters={},
            binding_parameters={},
        )
    with pytest.raises(ValueError, match="not a Candidate Collection"):
        implementation.execute(
            inputs={"candidates_a": []},
            node_parameters={},
            binding_parameters={},
        )
    with pytest.raises(ValueError, match="input partition"):
        implementation.execute(
            inputs={
                "candidates_a": left,
                "candidates_b": CandidateCollection(
                    "duplicate",
                    "protein.sequence",
                    [first],
                ),
            },
            node_parameters={},
            binding_parameters={},
        )


def test_score_union_deduplicates_only_identical_observations() -> None:
    implementation = CollectionOpsImplementation("merge_scores")
    observation = _observation()
    left = ScoreCollection("left", [observation])
    duplicate = ScoreCollection("duplicate", [replace(observation)])

    output = implementation.execute(
        inputs={"scores_b": duplicate, "scores_a": left},
        node_parameters={},
        binding_parameters={},
    )["scores"]

    assert output.entries == [observation]
    assert output.entries[0] is observation
    assert implementation.execute(
        inputs={"scores_c": ScoreCollection("empty", [])},
        node_parameters={},
        binding_parameters={},
    )["scores"].entries == []
    with pytest.raises(ValueError, match="conflicting values"):
        implementation.execute(
            inputs={
                "scores_a": left,
                "scores_b": ScoreCollection(
                    "conflict",
                    [replace(observation, value=0.75)],
                ),
            },
            node_parameters={},
            binding_parameters={},
        )
    with pytest.raises(ValueError, match="partition collision"):
        implementation.execute(
            inputs={
                "scores_a": left,
                "scores_b": ScoreCollection(
                    "collision",
                    [
                        replace(
                            observation,
                            source_partition="partition-b",
                        )
                    ],
                ),
            },
            node_parameters={},
            binding_parameters={},
        )
    with pytest.raises(ValueError, match="legacy subject-free"):
        implementation.execute(
            inputs={
                "scores_a": ScoreCollection(
                    "legacy",
                    [Score("confidence", 0.5)],
                )
            },
            node_parameters={},
            binding_parameters={},
        )
    with pytest.raises(ValueError, match="at least one connected"):
        implementation.execute(
            inputs={},
            node_parameters={},
            binding_parameters={},
        )
    with pytest.raises(ValueError, match="not a Score Collection"):
        implementation.execute(
            inputs={"scores_a": []},
            node_parameters={},
            binding_parameters={},
        )


def test_compiler_derives_exact_capabilities_through_score_union() -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    metric = ExactContractReference(
        **catalog.require_contract(
            "metric",
            "contract_test.collection_ops_value",
            VERSION,
        ).reference()
    )
    method = ExactContractReference(
        **catalog.require_contract(
            "method",
            "contract_test.collection_ops_source.a.method",
            VERSION,
        ).reference()
    )
    utility = ExactContractReference(
        **catalog.require_contract(
            "utility_transform",
            "contract_test.collection_ops_identity.a",
            VERSION,
        ).reference()
    )
    source_a = _source("a")
    source_b = _source("b")
    merge = WorkflowNodeInstance(
        node_id="merge",
        node_type_id="collection_ops.merge_scores",
        node_type_version=VERSION,
        binding_id="collection_ops.merge_scores.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="compile-collection-union",
        nodes=(source_a, source_b, merge),
        edges=(
            WorkflowEdge("source-a", "scores", "merge", "scores_a"),
            WorkflowEdge("source-b", "scores", "merge", "scores_b"),
        ),
        contract_lock=(),
        selection_objectives=(
            SelectionObjective(
                objective_id="partition-a-only",
                candidate_input=SelectionInput(
                    "source-a",
                    "candidates",
                ),
                score_collection_input=SelectionInput("merge", "scores"),
                source_partition="contract_test.partition.a",
                metric=metric,
                method=method,
                context_selector=IntrinsicObservationContext(),
                utility_transform=utility,
                utility_parameters={},
                weight=1.0,
            ),
        ),
    )

    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_revision=1,
        catalog=catalog,
    )

    assert compiled.execution_plan.selection_objectives[0].source_partition == (
        "contract_test.partition.a"
    )

    unknown_partition = replace(
        workflow,
        selection_objectives=(
            replace(
                workflow.selection_objectives[0],
                source_partition="contract_test.partition.unknown",
            ),
        ),
        contract_lock=(),
    )
    with pytest.raises(WorkflowCompileError) as rejected:
        compile_workflow(
            relock_workflow(unknown_partition, catalog),
            workflow_revision=2,
            catalog=catalog,
        )
    assert rejected.value.code == "unsatisfied_selection_objective"


def test_compiler_rejects_multiple_collections_on_one_optional_port() -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="invalid-collection-multiplicity",
        nodes=(
            _source("a"),
            _source("b"),
            WorkflowNodeInstance(
                node_id="merge",
                node_type_id="collection_ops.merge_scores",
                node_type_version=VERSION,
                binding_id="collection_ops.merge_scores.direct",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source-a", "scores", "merge", "scores_a"),
            WorkflowEdge("source-b", "scores", "merge", "scores_a"),
        ),
        contract_lock=(),
    )

    with pytest.raises(WorkflowCompileError) as rejected:
        compile_workflow(
            relock_workflow(workflow, catalog),
            workflow_revision=1,
            catalog=catalog,
        )
    assert rejected.value.code == "duplicate_input_connection"
