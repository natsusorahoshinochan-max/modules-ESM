"""Ticket 29 acceptance at the package, compiler, and public execution seams."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import (
    ModulePackageContractCase,
    SelectionInput,
    SelectionObjective,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    compile_workflow,
    relock_workflow,
    verify_module_package_contract,
)
from core.project import ProjectManager
from core.server import create_app
from core.workflow_v2 import WorkflowCompileError, WorkflowEdge
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)
from modules.selection.package import MODULE_PACKAGE
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal


VERSION = "2.0.0"
SOURCE_PARTITION = "contract_test.partition.a"


def _support_package():
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    return SOURCE_PACKAGE


def _catalog():
    return build_frozen_catalog((MODULE_PACKAGE, _support_package()))


def _reference(catalog, kind: str, contract_id: str) -> ExactContractReference:
    return ExactContractReference(
        **catalog.require_contract(kind, contract_id, VERSION).reference()
    )


def _source(*, candidate_count: int = 3) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.collection_ops_source",
        node_type_version=VERSION,
        binding_id="contract_test.collection_ops_source.a",
        binding_version=VERSION,
        node_parameters={"candidate_count": candidate_count},
        binding_parameters={},
    )


def _selection_node(
    operation: str,
    *,
    parameters: dict[str, object] | None = None,
) -> WorkflowNodeInstance:
    defaults: dict[str, object] = {
        "objective_id": "quality",
        "out_of_scope_policy": "error",
        "tie_policy": "candidate_id_ascending",
    }
    if operation in {"weighted_rank", "pareto", "diversity"}:
        defaults = {
            "objective_ids": ["quality"],
            "tie_policy": "candidate_id_ascending",
        }
    if operation == "filter":
        defaults.update({"operator": ">=", "threshold": 0.25})
    if operation in {"top_k", "diversity"}:
        defaults["k"] = 2
    defaults.update(parameters or {})
    return WorkflowNodeInstance(
        node_id="select",
        node_type_id=f"selection.{operation}",
        node_type_version=VERSION,
        binding_id=f"selection.{operation}.direct",
        binding_version=VERSION,
        node_parameters=defaults,
        binding_parameters={},
    )


def _objective(
    catalog,
    *,
    objective_id: str = "quality",
    candidate_node: str = "source",
    score_node: str = "source",
) -> SelectionObjective:
    return SelectionObjective(
        objective_id=objective_id,
        candidate_input=SelectionInput(candidate_node, "candidates"),
        score_collection_input=SelectionInput(score_node, "scores"),
        source_partition=SOURCE_PARTITION,
        metric=_reference(
            catalog,
            "metric",
            "contract_test.collection_ops_value",
        ),
        method=_reference(
            catalog,
            "method",
            "contract_test.collection_ops_source.a.method",
        ),
        context_selector=IntrinsicObservationContext(),
        utility_transform=_reference(
            catalog,
            "utility_transform",
            "contract_test.collection_ops_identity.a",
        ),
        utility_parameters={},
        weight=1,
        match_cardinality="exactly_one",
        missing_policy="error",
    )


def _workflow(
    catalog,
    operation: str,
    *,
    parameters: dict[str, object] | None = None,
    objective: SelectionObjective | None = None,
) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=f"selection-{operation}",
        nodes=(_source(), _selection_node(operation, parameters=parameters)),
        edges=(
            WorkflowEdge("source", "candidates", "select", "candidates"),
            WorkflowEdge("source", "scores", "select", "scores"),
        ),
        contract_lock=(),
        selection_objectives=(objective or _objective(catalog),),
    )


def test_public_catalog_has_three_selection_nodes_in_one_package() -> None:
    catalog = _catalog()
    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        response = client.get("/api/v2/catalog")
    assert response.status_code == 200
    contracts = {
        (contract.contract_kind, contract.contract_id): contract
        for contract in catalog.contracts
        if contract.contract_id.startswith("selection.")
    }

    operations = (
        "filter",
        "sort",
        "top_k",
        "weighted_rank",
        "pareto",
        "diversity",
    )
    assert set(contracts) == {
        (kind, f"selection.{operation}{suffix}")
        for operation in operations
        for kind, suffix in (
            ("node_type", ""),
            ("method", ".method"),
            ("binding", ".direct"),
        )
    }
    for operation in operations:
        node = contracts[("node_type", f"selection.{operation}")]
        assert [
            (port["name"], port["port_type"]["contract_id"])
            for port in node.descriptor["inputs"]
        ] == [
            ("candidates", "candidate.collection"),
            ("scores", "score.collection"),
        ]
        binding = contracts[("binding", f"selection.{operation}.direct")]
        selector = (
            {"objective_ids_parameter": "objective_ids"}
            if operation in {"weighted_rank", "pareto", "diversity"}
            else {"objective_id_parameter": "objective_id"}
        )
        assert binding.descriptor["selection_objective_consumption"] == {
            "schema_version": VERSION,
            "candidate_input_port": "candidates",
            "score_collection_input_port": "scores",
            **selector,
        }


@pytest.mark.parametrize("operation", ["filter", "sort", "top_k"])
def test_compiler_resolves_exact_selector_sources(operation: str) -> None:
    catalog = _catalog()
    workflow = _workflow(catalog, operation)

    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_revision=1,
        catalog=catalog,
    )

    assert compiled.execution_plan.selection_objectives == (
        _objective(catalog),
    )


def test_compiler_rejects_unknown_or_mismatched_selector_before_execution() -> None:
    catalog = _catalog()
    unknown = _workflow(
        catalog,
        "sort",
        parameters={"objective_id": "absent"},
    )
    with pytest.raises(
        WorkflowCompileError,
        match="does not resolve one Workflow Selection Objective",
    ):
        compile_workflow(
            relock_workflow(unknown, catalog),
            workflow_revision=1,
            catalog=catalog,
        )

    valid = _workflow(catalog, "sort")
    other_source = replace(
        _source(),
        node_id="other-source",
    )
    mismatched = replace(
        valid,
        nodes=(valid.nodes[0], other_source, valid.nodes[1]),
        edges=(
            WorkflowEdge(
                "other-source",
                "candidates",
                "select",
                "candidates",
            ),
            valid.edges[1],
        ),
    )
    with pytest.raises(
        WorkflowCompileError,
        match="Candidate input does not match",
    ):
        compile_workflow(
            relock_workflow(mismatched, catalog),
            workflow_revision=1,
            catalog=catalog,
        )


def _direct_implementation(operation: str):
    catalog = _catalog()
    plan = compile_workflow(
        relock_workflow(_workflow(catalog, operation), catalog),
        workflow_revision=1,
        catalog=catalog,
    ).execution_plan
    binding = catalog.require_contract(
        "binding",
        f"selection.{operation}.direct",
        VERSION,
    )
    implementation = catalog.require_factory(
        binding.contract_id,
        VERSION,
    ).build(
        execution_plan=plan,
        frozen_catalog=catalog,
        environment_configuration={},
        run_resources=None,
    )
    return catalog, implementation


def _runtime_values(catalog):
    metric = _reference(
        catalog,
        "metric",
        "contract_test.collection_ops_value",
    )
    method = _reference(
        catalog,
        "method",
        "contract_test.collection_ops_source.a.method",
    )
    candidates = CandidateCollection(
        "runtime-candidates",
        "protein.sequence",
        [
            Candidate(
                candidate_id,
                ProteinSequence(sequence),
                parent_ids=[f"parent-{candidate_id}"],
                metadata={"producer_slot": index},
            )
            for index, (candidate_id, sequence) in enumerate(
                (
                    ("candidate-z", "ACD"),
                    ("candidate-b", "ACE"),
                    ("candidate-a", "ACF"),
                )
            )
        ],
    )
    scores = ScoreCollection(
        "runtime-scores",
        [
            ScoreObservation(
                candidate_id=candidate_id,
                metric=metric,
                method=method,
                context=IntrinsicObservationContext(),
                value=value,
                source_partition=SOURCE_PARTITION,
            )
            for candidate_id, value in (
                ("candidate-z", 0.9),
                ("candidate-b", 0.5),
                ("candidate-a", 0.5),
            )
        ],
    )
    return candidates, scores


def test_filter_preserves_exact_candidate_objects_and_fails_closed() -> None:
    catalog, implementation = _direct_implementation("filter")
    candidates, scores = _runtime_values(catalog)

    output = implementation.execute(
        inputs={"candidates": candidates, "scores": scores},
        node_parameters={
            "objective_id": "quality",
            "operator": ">",
            "threshold": 0.5,
            "out_of_scope_policy": "error",
            "tie_policy": "candidate_id_ascending",
        },
        binding_parameters={},
    )["candidates"]

    assert output.items == [candidates.items[0]]
    assert output.items[0] is candidates.items[0]
    incomplete = ScoreCollection("missing", list(scores.entries[:-1]))
    with pytest.raises(ValueError, match="missing observation"):
        implementation.execute(
            inputs={"candidates": candidates, "scores": incomplete},
            node_parameters={
                "objective_id": "quality",
                "operator": ">",
                "threshold": 0.5,
                "out_of_scope_policy": "error",
                "tie_policy": "candidate_id_ascending",
            },
            binding_parameters={},
        )


def test_sort_and_top_k_use_utility_and_candidate_identity_ties() -> None:
    catalog, sorter = _direct_implementation("sort")
    candidates, scores = _runtime_values(catalog)
    common = {
        "objective_id": "quality",
        "out_of_scope_policy": "error",
        "tie_policy": "candidate_id_ascending",
    }

    sorted_candidates = sorter.execute(
        inputs={"candidates": candidates, "scores": scores},
        node_parameters=common,
        binding_parameters={},
    )["candidates"]

    assert [item.candidate_id for item in sorted_candidates.items] == [
        "candidate-z",
        "candidate-a",
        "candidate-b",
    ]
    assert sorted_candidates.items[1] is candidates.items[2]
    _, top_k = _direct_implementation("top_k")
    selected = top_k.execute(
        inputs={"candidates": candidates, "scores": scores},
        node_parameters={**common, "k": 2},
        binding_parameters={},
    )["candidates"]
    assert selected.items == [
        candidates.items[0],
        candidates.items[2],
    ]
    with pytest.raises(ValueError, match="cannot exceed"):
        top_k.execute(
            inputs={"candidates": candidates, "scores": scores},
            node_parameters={**common, "k": 4},
            binding_parameters={},
        )


def test_duplicate_conflicting_and_out_of_scope_observations_fail_closed() -> None:
    catalog, implementation = _direct_implementation("sort")
    candidates, scores = _runtime_values(catalog)
    parameters = {
        "objective_id": "quality",
        "out_of_scope_policy": "error",
        "tie_policy": "candidate_id_ascending",
    }

    duplicate = ScoreCollection(
        "duplicate",
        [*scores.entries, scores.entries[0]],
    )
    with pytest.raises(ValueError, match="duplicate observation"):
        implementation.execute(
            inputs={"candidates": candidates, "scores": duplicate},
            node_parameters=parameters,
            binding_parameters={},
        )
    conflict = ScoreCollection(
        "conflict",
        [*scores.entries, replace(scores.entries[0], value=0.1)],
    )
    with pytest.raises(ValueError, match="conflicting observation"):
        implementation.execute(
            inputs={"candidates": candidates, "scores": conflict},
            node_parameters=parameters,
            binding_parameters={},
        )
    out_of_scope = ScoreCollection(
        "out-of-scope",
        [
            *scores.entries,
            replace(scores.entries[0], candidate_id="candidate-ghost"),
        ],
    )
    with pytest.raises(ValueError, match="out-of-scope observation"):
        implementation.execute(
            inputs={"candidates": candidates, "scores": out_of_scope},
            node_parameters=parameters,
            binding_parameters={},
        )
    ignored_duplicate = ScoreCollection(
        "ignored-duplicate",
        [
            *scores.entries,
            replace(scores.entries[0], candidate_id="candidate-ghost"),
            replace(
                scores.entries[0],
                candidate_id="candidate-ghost",
                value=0.1,
            ),
        ],
    )
    ignored = implementation.execute(
        inputs={"candidates": candidates, "scores": ignored_duplicate},
        node_parameters={**parameters, "out_of_scope_policy": "ignore"},
        binding_parameters={},
    )["candidates"]
    assert [candidate.candidate_id for candidate in ignored.items] == [
        "candidate-z",
        "candidate-a",
        "candidate-b",
    ]


def test_all_three_nodes_pass_the_contract_test_kit(tmp_path: Path) -> None:
    catalog = _catalog()
    objective = _objective(catalog)
    cases = tuple(
        ModulePackageContractCase(
            case_id=f"selection-{operation}",
            node_type_id=f"selection.{operation}",
            node_type_version=VERSION,
            binding_id=f"selection.{operation}.direct",
            binding_version=VERSION,
            node_parameters=_selection_node(operation).node_parameters,
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token=f"selection-{operation}-v1",
            workflow_nodes=(_source(),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "candidates",
                    "contract-test-node",
                    "candidates",
                ),
                WorkflowEdge(
                    "source",
                    "scores",
                    "contract-test-node",
                    "scores",
                ),
            ),
            selection_objectives=(objective,),
            expected_candidate_counts={
                "candidates": (
                    2
                    if operation in {"top_k", "diversity"}
                    else 3
                )
            },
        )
        for operation in (
            "filter",
            "sort",
            "top_k",
            "weighted_rank",
            "pareto",
            "diversity",
        )
    )

    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=cases,
        supporting_registrations=(_support_package(),),
        work_root=tmp_path,
    )

    assert all(case.status == "succeeded" for case in report.case_reports)


def test_public_execution_is_cache_replay_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "selection public cache"
    ).id
    workflow = replace(
        _workflow(catalog, "top_k"),
        workflow_id=project_id,
    )
    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": workflow.to_public(),
            },
        )
        assert saved.status_code == 200
        revision = saved.json()["workflow_revision"]
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": revision},
        )
        assert relocked.status_code == 200
        revision = relocked.json()["workflow_revision"]
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": revision,
                "workflow": relocked.json()["workflow"],
            },
        )
        assert compiled.status_code == 200

        projections = []
        for request_id in ("selection-first", "selection-second"):
            started = client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": revision,
                    "compile_id": compiled.json()["compile_id"],
                    "client_request_id": request_id,
                },
            )
            assert started.status_code == 202
            projections.append(
                wait_for_testclient_run_terminal(
                    client,
                    project_id,
                    started.json()["run_id"],
                )
            )

    selected_ids = []
    for projection in projections:
        assert projection["status"] == "succeeded"
        selected = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "select"
            and output["output_port"] == "candidates"
        )
        ids = [
            value["fields"]["candidate_id"]
            for value in selected["values"][0]["fields"]["items"]
        ]
        assert len(ids) == 2
        assert ids == sorted(ids)
        selected_ids.append(ids)
    assert selected_ids[0] == selected_ids[1]
    second_select = next(
        disposition
        for disposition in projections[1]["node_dispositions"]
        if disposition["node_id"] == "select"
    )
    assert second_select["resolution"] == "cache_replayed"


def test_changing_resolved_objective_invalidates_selection_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "selection objective cache identity"
    ).id
    workflow = replace(
        _workflow(catalog, "top_k"),
        workflow_id=project_id,
    )

    def save_compile_run(
        client: TestClient,
        document: WorkflowDocument,
        *,
        expected_revision: int,
        request_id: str,
    ):
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": expected_revision,
                "workflow": document.to_public(),
            },
        )
        assert saved.status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": saved.json()["workflow_revision"]},
        )
        assert relocked.status_code == 200
        revision = relocked.json()["workflow_revision"]
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": revision,
                "workflow": relocked.json()["workflow"],
            },
        )
        assert compiled.status_code == 200
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": revision,
                "compile_id": compiled.json()["compile_id"],
                "client_request_id": request_id,
            },
        )
        assert started.status_code == 202
        return (
            revision,
            wait_for_testclient_run_terminal(
                client,
                project_id,
                started.json()["run_id"],
            ),
        )

    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        revision, first = save_compile_run(
            client,
            workflow,
            expected_revision=0,
            request_id="objective-weight-one",
        )
        changed = replace(
            workflow,
            selection_objectives=(
                replace(workflow.selection_objectives[0], weight=2),
            ),
            contract_lock=(),
        )
        _, second = save_compile_run(
            client,
            changed,
            expected_revision=revision,
            request_id="objective-weight-two",
        )

    first_output = next(
        output
        for output in first["outputs"]
        if output["node_id"] == "select"
    )
    second_output = next(
        output
        for output in second["outputs"]
        if output["node_id"] == "select"
    )
    assert first_output["result_identity"] != second_output["result_identity"]
    assert (
        first_output["values"][0]["fields"]["collection_id"]
        != second_output["values"][0]["fields"]["collection_id"]
    )
    second_selection = next(
        disposition
        for disposition in second["node_dispositions"]
        if disposition["node_id"] == "select"
    )
    assert second_selection["resolution"] == "executed"
