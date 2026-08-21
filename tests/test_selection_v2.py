"""Ticket 29 acceptance at the package, compiler, and public execution seams."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import (
    ModulePackageContractCase,
    ObservationSelector,
    PortValueError,
    SelectionError,
    SelectionInput,
    SelectionObjective,
    WorkflowCommit,
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
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)
from modules.selection.package import MODULE_PACKAGE
from tests.fixtures.public_v2 import (
    retrieve_typed_output_values,
    wait_for_testclient_run_terminal,
)
from tests.fixtures.scientific_operation import build_operation, operation_call


VERSION = "2.1.0"
NODE_BINDING_VERSION = "5.0.0"
SOURCE_NODE_VERSION = "4.0.0"
SCORER_NODE_VERSION = "5.0.0"
SOURCE_PARTITION = "contract_test.partition.a"


def _assert_workflow_commit_owner(
    app: FastAPI,
    project_id: str,
    *,
    source_draft_revision: int,
    workflow_commit_revision: int,
) -> WorkflowCommit:
    owner = app.state.workflow_authoring_v2
    commit = owner.load_active_commit(project_id)
    draft = owner.load_draft(project_id)
    compiled = owner.require_compiled(
        project_id,
        workflow_commit_id=commit.workflow_commit_id,
    )
    plan = compiled.execution_plan

    assert commit.source_draft_revision == source_draft_revision
    assert commit.source_draft_revision == draft.draft_revision
    assert commit.source_draft_digest == draft.draft_digest
    assert commit.workflow_commit_revision == workflow_commit_revision
    assert plan.workflow_commit_revision == commit.workflow_commit_revision
    assert plan.workflow_digest == commit.workflow_digest
    assert plan.catalog_contract_digest == commit.catalog_contract_digest
    assert plan.contract_lock_digest == commit.contract_lock_digest
    assert plan.execution_plan_digest == commit.execution_plan_digest
    assert commit.workflow_commit_id == plan.execution_plan_digest.replace(
        "sha256:",
        "workflow-commit-",
    )
    return commit


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
        node_type_version=SOURCE_NODE_VERSION,
        binding_id="contract_test.collection_ops_source.a",
        binding_version=SOURCE_NODE_VERSION,
        node_parameters={"candidate_count": candidate_count},
        binding_parameters={},
    )


def _scorer() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="scorer",
        node_type_id="contract_test.collection_ops_scorer",
        node_type_version=SCORER_NODE_VERSION,
        binding_id="contract_test.collection_ops_scorer.a",
        binding_version=SCORER_NODE_VERSION,
        node_parameters={},
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
    if operation == "filter":
        defaults = {
            "selector_id": "quality",
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
        node_type_version=NODE_BINDING_VERSION,
        binding_id=f"selection.{operation}.direct",
        binding_version=NODE_BINDING_VERSION,
        node_parameters=defaults,
        binding_parameters={},
    )


def _objective(
    catalog,
    *,
    objective_id: str = "quality",
    candidate_node: str = "source",
    score_node: str = "scorer",
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
            "contract_test.collection_ops_scorer.method",
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


def _selector(
    catalog,
    *,
    selector_id: str = "quality",
    candidate_node: str = "source",
    score_node: str = "scorer",
) -> ObservationSelector:
    return ObservationSelector(
        selector_id=selector_id,
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
            "contract_test.collection_ops_scorer.method",
        ),
        context_selector=IntrinsicObservationContext(),
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
        nodes=(
            _source(),
            _scorer(),
            _selection_node(operation, parameters=parameters),
        ),
        edges=(
            WorkflowEdge("source", "candidates", "scorer", "candidates"),
            WorkflowEdge("source", "candidates", "select", "candidates"),
            WorkflowEdge("scorer", "scores", "select", "scores"),
        ),
        contract_lock=(),
        observation_selectors=(
            (_selector(catalog),)
            if operation == "filter"
            else ()
        ),
        selection_objectives=(
            ()
            if operation == "filter"
            else (objective or _objective(catalog),)
        ),
    )


def test_public_catalog_has_three_selection_nodes_in_one_package() -> None:
    catalog = _catalog()
    app = create_app(frozen_catalog_override=catalog)
    with TestClient(app) as client:
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
        assert node.contract_version == NODE_BINDING_VERSION
        assert [
            (
                port["name"],
                port["port_type"]["contract_id"],
                port["port_type"]["contract_version"],
            )
            for port in node.descriptor["inputs"]
        ] == [
            ("candidates", "candidate.collection", "4.0.0"),
            ("scores", "score.collection", "5.0.0"),
        ]
        binding = contracts[("binding", f"selection.{operation}.direct")]
        method = contracts[("method", f"selection.{operation}.method")]
        assert binding.contract_version == NODE_BINDING_VERSION
        assert binding.descriptor["method"]["contract_version"] == "4.0.0"
        assert method.contract_version == "4.0.0"
        assert method.descriptor["algorithm_identity"][
            "candidate_score_join"
        ] == "exact-candidate-data-reference"
        selector = (
            {"objective_ids_parameter": "objective_ids"}
            if operation in {"weighted_rank", "pareto", "diversity"}
            else {"objective_id_parameter": "objective_id"}
        )
        if operation == "filter":
            assert binding.descriptor[
                "observation_selector_consumption"
            ] == {
                "schema_version": VERSION,
                "candidate_input_port": "candidates",
                "score_collection_input_port": "scores",
                "candidate_output_port": "candidates",
                "selector_id_parameter": "selector_id",
            }
            assert "selection_objective_consumption" not in binding.descriptor
        else:
            assert binding.descriptor["selection_objective_consumption"] == {
                "schema_version": VERSION,
                "candidate_input_port": "candidates",
                "score_collection_input_port": "scores",
                "candidate_output_port": "candidates",
                **selector,
            }


@pytest.mark.parametrize("operation", ["filter", "sort", "top_k"])
def test_compiler_resolves_exact_selector_sources(operation: str) -> None:
    catalog = _catalog()
    workflow = _workflow(catalog, operation)

    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_commit_revision=1,
        catalog=catalog,
    )

    assert compiled.execution_plan.workflow_commit_revision == 1

    if operation == "filter":
        assert compiled.execution_plan.observation_selectors == (
            _selector(catalog),
        )
        assert compiled.execution_plan.selection_objectives == ()
    else:
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
            workflow_commit_revision=1,
            catalog=catalog,
        )

    valid = _workflow(catalog, "sort")
    other_source = replace(
        _source(),
        node_id="other-source",
    )
    mismatched = replace(
        valid,
        nodes=(*valid.nodes[:2], other_source, valid.nodes[2]),
        edges=(
            valid.edges[0],
            WorkflowEdge(
                "other-source",
                "candidates",
                "select",
                "candidates",
            ),
            valid.edges[2],
        ),
    )
    with pytest.raises(
        WorkflowCompileError,
        match="Candidate input does not match",
    ):
        compile_workflow(
            relock_workflow(mismatched, catalog),
            workflow_commit_revision=1,
            catalog=catalog,
        )


def _direct_implementation(operation: str):
    catalog = _catalog()
    plan = compile_workflow(
        relock_workflow(_workflow(catalog, operation), catalog),
        workflow_commit_revision=1,
        catalog=catalog,
    ).execution_plan
    binding_id = f"selection.{operation}.direct"
    implementation = build_operation(
        catalog,
        binding_id,
        None,
        binding_version=NODE_BINDING_VERSION,
        selection_objectives=plan.selection_objectives,
        observation_selectors=plan.observation_selectors,
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
        "contract_test.collection_ops_scorer.method",
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
    sequence_port = catalog.require_port_type(
        "protein.sequence",
        "3.0.0",
    )
    subjects = {
        candidate.candidate_id: CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id="protein.sequence",
            content_digest=sequence_port.content_digest(candidate.data),
        )
        for candidate in candidates.items
    }
    scores = ScoreCollection(
        "runtime-scores",
        [
            ScoreObservation(
                subject=subjects[candidate_id],
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


@pytest.mark.parametrize("operation", ("sort", "weighted_rank"))
def test_utility_selection_joins_by_complete_admitted_cdr(
    operation: str,
) -> None:
    catalog, implementation = _direct_implementation(operation)
    candidates, scores = _runtime_values(catalog)
    mismatched = ScoreCollection(
        "mismatched-subject",
        [
            replace(
                scores.entries[0],
                subject=replace(
                    scores.entries[0].subject,
                    content_digest=f"sha256:{'0' * 64}",
                ),
            ),
            *scores.entries[1:],
        ],
    )

    with pytest.raises(
        SelectionError,
        match="exact Candidate input",
    ):
        implementation.execute(operation_call(
            catalog=catalog,
            binding_id=f"selection.{operation}.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={"candidates": candidates, "scores": mismatched},
            node_parameters=_selection_node(operation).node_parameters,
            binding_parameters={},
        ))


def test_filter_preserves_exact_candidate_objects_and_fails_closed() -> None:
    catalog, implementation = _direct_implementation("filter")
    candidates, scores = _runtime_values(catalog)

    call = operation_call(
        catalog=catalog,
        binding_id="selection.filter.direct",
        binding_version=NODE_BINDING_VERSION,
        inputs={"candidates": candidates, "scores": scores},
        node_parameters={
            "selector_id": "quality",
            "operator": ">",
            "threshold": 0.5,
            "out_of_scope_policy": "error",
            "tie_policy": "candidate_id_ascending",
        },
        binding_parameters={},
    )
    output = implementation.execute(call)["candidates"]
    admitted_candidates = call.inputs["candidates"].value

    assert output.items == (admitted_candidates.items[0],)
    assert output.items[0] is admitted_candidates.items[0]
    incomplete = ScoreCollection("missing", list(scores.entries[:-1]))
    with pytest.raises(ValueError, match="missing observation"):
        implementation.execute(operation_call(
            catalog=catalog,
            binding_id="selection.filter.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={"candidates": candidates, "scores": incomplete},
            node_parameters={
                "selector_id": "quality",
                "operator": ">",
                "threshold": 0.5,
                "out_of_scope_policy": "error",
                "tie_policy": "candidate_id_ascending",
            },
            binding_parameters={},
        ))


def test_sort_and_top_k_use_utility_and_candidate_identity_ties() -> None:
    catalog, sorter = _direct_implementation("sort")
    candidates, scores = _runtime_values(catalog)
    common = {
        "objective_id": "quality",
        "out_of_scope_policy": "error",
        "tie_policy": "candidate_id_ascending",
    }

    sort_call = operation_call(
        catalog=catalog,
        binding_id="selection.sort.direct",
        binding_version=NODE_BINDING_VERSION,
        inputs={"candidates": candidates, "scores": scores},
        node_parameters=common,
        binding_parameters={},
    )
    sorted_candidates = sorter.execute(sort_call)["candidates"]

    assert [item.candidate_id for item in sorted_candidates.items] == [
        "candidate-z",
        "candidate-a",
        "candidate-b",
    ]
    assert (
        sorted_candidates.items[1]
        is sort_call.inputs["candidates"].value.items[2]
    )
    _, top_k = _direct_implementation("top_k")
    selected = top_k.execute(operation_call(
        catalog=catalog,
        binding_id="selection.top_k.direct",
        binding_version=NODE_BINDING_VERSION,
        inputs={"candidates": candidates, "scores": scores},
        node_parameters={**common, "k": 2},
        binding_parameters={},
    ))["candidates"]
    assert [item.candidate_id for item in selected.items] == [
        "candidate-z",
        "candidate-a",
    ]
    with pytest.raises(ValueError, match="cannot exceed"):
        top_k.execute(operation_call(
            catalog=catalog,
            binding_id="selection.top_k.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={"candidates": candidates, "scores": scores},
            node_parameters={**common, "k": 4},
            binding_parameters={},
        ))


def test_conflicting_and_out_of_scope_observations_fail_closed() -> None:
    catalog, implementation = _direct_implementation("sort")
    candidates, scores = _runtime_values(catalog)
    parameters = {
        "objective_id": "quality",
        "out_of_scope_policy": "error",
        "tie_policy": "candidate_id_ascending",
    }

    conflict = ScoreCollection(
        "conflict",
        [*scores.entries, replace(scores.entries[0], value=0.1)],
    )
    with pytest.raises(PortValueError, match="conflicting values"):
        implementation.execute(operation_call(
            catalog=catalog,
            binding_id="selection.sort.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={"candidates": candidates, "scores": conflict},
            node_parameters=parameters,
            binding_parameters={},
        ))
    out_of_scope = ScoreCollection(
        "out-of-scope",
        [
            *scores.entries,
            replace(
                scores.entries[0],
                subject=replace(
                    scores.entries[0].subject,
                    candidate_id="candidate-ghost",
                ),
            ),
        ],
    )
    with pytest.raises(ValueError, match="out-of-scope observation"):
        implementation.execute(operation_call(
            catalog=catalog,
            binding_id="selection.sort.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={"candidates": candidates, "scores": out_of_scope},
            node_parameters=parameters,
            binding_parameters={},
        ))
    ignored_out_of_scope = ScoreCollection(
        "ignored-out-of-scope",
        [
            *scores.entries,
            replace(
                scores.entries[0],
                subject=replace(
                    scores.entries[0].subject,
                    candidate_id="candidate-ghost",
                ),
            ),
        ],
    )
    ignored = implementation.execute(operation_call(
        catalog=catalog,
        binding_id="selection.sort.direct",
        binding_version=NODE_BINDING_VERSION,
        inputs={"candidates": candidates, "scores": ignored_out_of_scope},
        node_parameters={**parameters, "out_of_scope_policy": "ignore"},
        binding_parameters={},
    ))["candidates"]
    assert [candidate.candidate_id for candidate in ignored.items] == [
        "candidate-z",
        "candidate-a",
        "candidate-b",
    ]


def test_all_three_nodes_pass_the_contract_test_kit(tmp_path: Path) -> None:
    catalog = _catalog()
    objective = _objective(catalog)
    selector = _selector(catalog)
    cases = tuple(
        ModulePackageContractCase(
            case_id=f"selection-{operation}",
            node_type_id=f"selection.{operation}",
            node_type_version=NODE_BINDING_VERSION,
            binding_id=f"selection.{operation}.direct",
            binding_version=NODE_BINDING_VERSION,
            node_parameters=_selection_node(operation).node_parameters,
            binding_parameters={},
            environment_values={},
            workflow_nodes=(_source(), _scorer()),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "candidates",
                    "scorer",
                    "candidates",
                ),
                WorkflowEdge(
                    "source",
                    "candidates",
                    "contract-test-node",
                    "candidates",
                ),
                WorkflowEdge(
                    "scorer",
                    "scores",
                    "contract-test-node",
                    "scores",
                ),
            ),
            observation_selectors=(
                (selector,) if operation == "filter" else ()
            ),
            selection_objectives=(
                () if operation == "filter" else (objective,)
            ),
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
    app = create_app(frozen_catalog_override=catalog)
    with TestClient(app) as client:
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow.to_public(),
            },
        )
        assert committed.status_code == 200
        _assert_workflow_commit_owner(
            app,
            project_id,
            source_draft_revision=1,
            workflow_commit_revision=1,
        )

        projections = []
        for request_id in ("selection-first", "selection-second"):
            started = client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_commit_id": committed.json()[
                        "workflow_commit_id"
                    ],
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
        selected_values = []
        for projection in projections:
            selected = next(
                output
                for output in projection["outputs"]
                if output["node_id"] == "select"
                and output["output_port"] == "candidates"
            )
            selected_values.append(
                retrieve_typed_output_values(
                    client,
                    project_id,
                    projection["run_id"],
                    selected,
                )[0]
            )

    selected_ids = []
    for projection, selected_value in zip(
        projections,
        selected_values,
        strict=True,
    ):
        assert projection["status"] == "succeeded"
        selected = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "select"
            and output["output_port"] == "candidates"
        )
        ids = [
            value["fields"]["candidate_id"]
            for value in selected_value["fields"]["items"]
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

    def commit_run(
        client: TestClient,
        document: WorkflowDocument,
        *,
        expected_commit_revision: int,
        request_id: str,
    ):
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": document.to_public(),
            },
        )
        assert committed.status_code == 200
        receipt = committed.json()
        commit = _assert_workflow_commit_owner(
            app,
            project_id,
            source_draft_revision=expected_commit_revision,
            workflow_commit_revision=expected_commit_revision,
        )
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": receipt["workflow_commit_id"],
                "client_request_id": request_id,
            },
        )
        assert started.status_code == 202
        return (
            commit.source_draft_revision,
            wait_for_testclient_run_terminal(
                client,
                project_id,
                started.json()["run_id"],
            ),
        )

    app = create_app(frozen_catalog_override=catalog)
    with TestClient(app) as client:
        _, first = commit_run(
            client,
            workflow,
            expected_commit_revision=1,
            request_id="objective-weight-one",
        )
        changed = replace(
            workflow,
            selection_objectives=(
                replace(workflow.selection_objectives[0], weight=2),
            ),
            contract_lock=(),
        )
        _, second = commit_run(
            client,
            changed,
            expected_commit_revision=2,
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
        first_value = retrieve_typed_output_values(
            client,
            project_id,
            first["run_id"],
            first_output,
        )[0]
        second_value = retrieve_typed_output_values(
            client,
            project_id,
            second["run_id"],
            second_output,
        )[0]

    assert first_output["result_identity"] != second_output["result_identity"]
    assert (
        first_value["fields"]["collection_id"]
        != second_value["fields"]["collection_id"]
    )
    second_selection = next(
        disposition
        for disposition in second["node_dispositions"]
        if disposition["node_id"] == "select"
    )
    assert second_selection["resolution"] == "executed"
