"""Public v2 contracts for partition-preserving collection operations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core import (
    ModulePackageContractCase,
    SelectionInput,
    SelectionObjective,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    build_discovered_frozen_catalog,
    verify_module_package_contract,
)
from core.port_types import PORT_VALUE_NAMESPACE, canonical_json_bytes
from core.project import ProjectManager
from core.server import create_app
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    ExactContractReference,
    IntrinsicObservationContext,
)
from modules.collection_ops.package import MODULE_PACKAGE
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal


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


def _public_collection_contracts() -> dict[tuple[str, str], dict]:
    catalog = build_discovered_frozen_catalog()
    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        response = client.get("/api/v2/catalog")
    assert response.status_code == 200
    return {
        (
            contract["reference"]["contract_kind"],
            contract["reference"]["contract_id"],
        ): contract["descriptor"]
        for contract in response.json()["contracts"]
        if contract["reference"]["contract_id"].startswith(
            "collection_ops."
        )
    }


def test_public_catalog_has_two_exact_collection_operation_nodes() -> None:
    contracts = _public_collection_contracts()

    assert set(contracts) == {
        ("binding", "collection_ops.concat_candidates.direct"),
        ("binding", "collection_ops.merge_scores.direct"),
        ("method", "collection_ops.concat_candidates.method"),
        ("method", "collection_ops.merge_scores.method"),
        ("node_type", "collection_ops.concat_candidates"),
        ("node_type", "collection_ops.merge_scores"),
    }
    assert not any(
        "aggregate" in contract_id for _, contract_id in contracts
    )


def test_collection_ports_and_score_union_are_closed_and_versioned() -> None:
    contracts = _public_collection_contracts()
    candidates = contracts[
        ("node_type", "collection_ops.concat_candidates")
    ]
    scores = contracts[("node_type", "collection_ops.merge_scores")]
    score_binding = contracts[
        ("binding", "collection_ops.merge_scores.direct")
    ]

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
    assert score_binding["produced_observations"] == []
    assert score_binding["observation_propagation"] == {
        "schema_version": VERSION,
        "mode": "union",
        "output_port": "scores",
        "input_ports": ["scores_a", "scores_b", "scores_c"],
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
    monkeypatch: pytest.MonkeyPatch,
    *,
    operation: str,
    counts: tuple[int, int] = (2, 1),
    connected_partitions: tuple[str, ...] = ("a", "b"),
) -> tuple[object, dict[str, object], dict[str, object], tuple[dict, ...]]:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir(parents=True)
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    port = "candidates" if operation == "concat_candidates" else "scores"
    target_port = (
        "candidates" if operation == "concat_candidates" else "scores"
    )
    project_id = ProjectManager(
        root_dir=tmp_path / "project"
    ).create(
        f"collection operations {operation}"
    ).id
    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        workflow = WorkflowDocument(
            schema_version=VERSION,
            workflow_id=project_id,
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
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": workflow.to_public(),
            },
        )
        assert saved.status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={
                "workflow_revision": saved.json()["workflow_revision"],
            },
        )
        assert relocked.status_code == 200
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": relocked.json()[
                    "workflow_revision"
                ],
                "workflow": relocked.json()["workflow"],
            },
        )
        assert compiled.status_code == 200

        def run(request_id: str) -> dict[str, object]:
            started = client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": relocked.json()[
                        "workflow_revision"
                    ],
                    "compile_id": compiled.json()["compile_id"],
                    "client_request_id": request_id,
                },
            )
            assert started.status_code == 202
            return wait_for_testclient_run_terminal(
                client,
                project_id,
                started.json()["run_id"],
            )

        first = run("collection-ops-first")
        second = run("collection-ops-second")
        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/"
            f"{second['run_id']}/events"
        ) as websocket:
            replay_messages: list[dict] = []
            try:
                while True:
                    replay_messages.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000
        replay_events = tuple(
            message
            for message in replay_messages
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        )
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, first, second, replay_events = (
        _run_public_collection_workflow(
            tmp_path,
            monkeypatch,
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, first, second, replay_events = (
        _run_public_collection_workflow(
            tmp_path,
            monkeypatch,
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, empty_first, empty_replay, _ = (
        _run_public_collection_workflow(
            tmp_path / "empty",
            monkeypatch,
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
            monkeypatch,
            operation="merge_scores",
            connected_partitions=(),
        )
    )
    assert absent_first["status"] == absent_replay["status"] == "failed"
    assert not any(
        output["node_id"] == "collection-op"
        for output in absent_first["outputs"]
    )


def _compile_through_public_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: object,
    workflow: WorkflowDocument,
):
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir(parents=True)
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(
        root_dir=tmp_path / "project"
    ).create(workflow.workflow_id).id
    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        public_workflow = replace(
            workflow,
            workflow_id=project_id,
            contract_lock=(),
        )
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": public_workflow.to_public(),
            },
        )
        assert saved.status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={
                "workflow_revision": saved.json()["workflow_revision"],
            },
        )
        assert relocked.status_code == 200
        return client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": relocked.json()[
                    "workflow_revision"
                ],
                "workflow": relocked.json()["workflow"],
            },
        )


def _run_through_public_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: object,
    workflow: WorkflowDocument,
) -> tuple[dict, tuple[dict, ...]]:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir(parents=True)
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(
        root_dir=tmp_path / "project"
    ).create(workflow.workflow_id).id
    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        public_workflow = replace(
            workflow,
            workflow_id=project_id,
            contract_lock=(),
        )
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": public_workflow.to_public(),
            },
        )
        assert saved.status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={
                "workflow_revision": saved.json()["workflow_revision"],
            },
        )
        assert relocked.status_code == 200
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": relocked.json()[
                    "workflow_revision"
                ],
                "workflow": relocked.json()["workflow"],
            },
        )
        assert compiled.status_code == 200
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": relocked.json()[
                    "workflow_revision"
                ],
                "compile_id": compiled.json()["compile_id"],
                "client_request_id": "collection-ops-failure-case",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )
        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            messages: list[dict] = []
            try:
                while True:
                    messages.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000
    events = tuple(
        message
        for message in messages
        if message["event"]["type"] not in {
            "replay_started",
            "replay_complete",
        }
    )
    return projection, events


def _scorer(partition: str, binding: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=f"scorer-{partition}",
        node_type_id="contract_test.collection_ops_scorer",
        node_type_version=VERSION,
        binding_id=f"contract_test.collection_ops_scorer.{binding}",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )


def _score_union_workflow(second_binding: str) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=f"score-union-{second_binding}",
        nodes=(
            _source("a"),
            _scorer("left", "low"),
            _scorer("right", second_binding),
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
            WorkflowEdge(
                "source-a",
                "candidates",
                "scorer-left",
                "candidates",
            ),
            WorkflowEdge(
                "source-a",
                "candidates",
                "scorer-right",
                "candidates",
            ),
            WorkflowEdge("scorer-left", "scores", "merge", "scores_a"),
            WorkflowEdge("scorer-right", "scores", "merge", "scores_b"),
        ),
        contract_lock=(),
    )


@pytest.mark.parametrize(
    ("second_binding", "expected_status"),
    (
        ("low", "succeeded"),
        ("high", "failed"),
        ("collision", "failed"),
    ),
)
def test_public_score_union_fails_closed_on_dynamic_contradictions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    second_binding: str,
    expected_status: str,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projection, _ = _run_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=_score_union_workflow(second_binding),
    )

    assert projection["status"] == expected_status
    merged_outputs = [
        output
        for output in projection["outputs"]
        if output["node_id"] == "merge"
        and output["output_port"] == "scores"
    ]
    if second_binding == "low":
        assert len(merged_outputs) == 1
        merged = _decoded_outputs(catalog, projection)[
            ("merge", "scores")
        ]
        assert len(merged.entries) == 1
    else:
        assert merged_outputs == []


def test_public_collection_operations_reject_candidate_partition_aliasing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="candidate-input-partition-alias",
        nodes=(
            _source("a"),
            WorkflowNodeInstance(
                node_id="concat",
                node_type_id="collection_ops.concat_candidates",
                node_type_version=VERSION,
                binding_id="collection_ops.concat_candidates.direct",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "concat",
                "candidates_a",
            ),
            WorkflowEdge(
                "source-a",
                "candidates",
                "concat",
                "candidates_b",
            ),
        ),
        contract_lock=(),
    )

    projection, _ = _run_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "concat"
        for output in projection["outputs"]
    )


def test_public_score_merge_rejects_legacy_subject_free_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="legacy-score-rejection",
        nodes=(
            WorkflowNodeInstance(
                node_id="legacy",
                node_type_id="contract_test.collection_ops_legacy_scores",
                node_type_version=VERSION,
                binding_id=(
                    "contract_test.collection_ops_legacy_scores.direct"
                ),
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
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
            WorkflowEdge("legacy", "scores", "merge", "scores_a"),
        ),
        contract_lock=(),
    )

    projection, _ = _run_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "merge"
        for output in projection["outputs"]
    )


def test_compiler_derives_exact_capabilities_through_score_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    compiled = _compile_through_public_rest(
        tmp_path / "accepted",
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert compiled.status_code == 200

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
    rejected = _compile_through_public_rest(
        tmp_path / "unknown",
        monkeypatch,
        catalog=catalog,
        workflow=unknown_partition,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "compile_rejected"
    assert rejected.json()["error"]["details"]["issues"][0]["code"] == (
        "unsatisfied_selection_objective"
    )


def test_compiler_rejects_multiple_collections_on_one_optional_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    rejected = _compile_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "compile_rejected"
    assert rejected.json()["error"]["details"]["issues"][0]["code"] == (
        "duplicate_input_connection"
    )


def test_compiler_rejects_a_malformed_optional_collection_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="malformed-optional-score-input",
        nodes=(
            _source("a"),
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
            WorkflowEdge(
                "source-a",
                "candidates",
                "merge",
                "scores_a",
            ),
        ),
        contract_lock=(),
    )

    rejected = _compile_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"]["issues"][0]["code"] == (
        "port_type_mismatch"
    )
