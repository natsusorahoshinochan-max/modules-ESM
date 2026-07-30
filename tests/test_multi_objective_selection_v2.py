"""Ticket 30 acceptance for explicit multi-objective selection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import core.run_execution_v2 as run_execution_v2
from core import (
    ModulePackageContractCase,
    PairwiseContextSelector,
    SelectionInput,
    SelectionObjective,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    canonical_json_bytes,
    compile_workflow,
    relock_workflow,
    verify_module_package_contract,
)
from core.scoring_v2 import SelectionError
from core.project import ProjectManager
from core.server import create_app
from core.workflow_v2 import WorkflowCompileError, WorkflowEdge
from datatypes import ExactContractReference, ScoreCollection
from modules.selection.package import MODULE_PACKAGE
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from tests.fixtures.multi_objective_selection_sources.package import (
    FIXED_PARTITION,
    NORMALIZATION,
    PAIRED_PARTITION,
    MODULE_PACKAGE as SOURCE_PACKAGE,
)
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal


VERSION = "2.0.0"
OPERATIONS = ("weighted_rank", "pareto", "diversity")


def _catalog():
    return build_frozen_catalog(
        (
            MODULE_PACKAGE,
            STRUCTURE_COMPARISON_PACKAGE,
            SOURCE_PACKAGE,
        )
    )


def _reference(catalog, kind: str, contract_id: str) -> ExactContractReference:
    return ExactContractReference(
        **catalog.require_contract(kind, contract_id, VERSION).reference()
    )


def _source() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="canonical-source",
        node_type_id="contract_test.multi_objective_selection_source",
        node_type_version=VERSION,
        binding_id="contract_test.multi_objective_selection_source.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )


def _selection(operation: str) -> WorkflowNodeInstance:
    parameters: dict[str, object] = {
        "objective_ids": ["fixed-3gb1", "paired-esm3"],
        "tie_policy": "candidate_id_ascending",
    }
    if operation == "diversity":
        parameters["k"] = 3
    return WorkflowNodeInstance(
        node_id="select",
        node_type_id=f"selection.{operation}",
        node_type_version=VERSION,
        binding_id=f"selection.{operation}.direct",
        binding_version=VERSION,
        node_parameters=parameters,
        binding_parameters={},
    )


def _objectives(catalog) -> tuple[SelectionObjective, SelectionObjective]:
    candidate_input = SelectionInput("canonical-source", "candidates")
    score_input = SelectionInput("canonical-source", "scores")
    common = {
        "candidate_input": candidate_input,
        "score_collection_input": score_input,
        "metric": _reference(
            catalog,
            "metric",
            "structure_comparison.tm_score",
        ),
        "method": _reference(
            catalog,
            "method",
            "contract_test.multi_objective_selection_source.method",
        ),
        "utility_parameters": {},
        "match_cardinality": "exactly_one",
        "missing_policy": "error",
    }
    return (
        SelectionObjective(
            objective_id="fixed-3gb1",
            context_selector=PairwiseContextSelector(
                pairing_mode="fixed_reference",
                normalization=NORMALIZATION,
            ),
            utility_transform=_reference(
                catalog,
                "utility_transform",
                "contract_test.tm_score.fixed_3gb1.identity",
            ),
            weight=0.7,
            source_partition=FIXED_PARTITION,
            **common,
        ),
        SelectionObjective(
            objective_id="paired-esm3",
            context_selector=PairwiseContextSelector(
                pairing_mode="per_subject_counterpart",
                normalization=NORMALIZATION,
            ),
            utility_transform=_reference(
                catalog,
                "utility_transform",
                "contract_test.tm_score.paired_esm3.identity",
            ),
            weight=0.3,
            source_partition=PAIRED_PARTITION,
            **common,
        ),
    )


def _workflow(catalog, operation: str) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=f"multi-objective-{operation}",
        nodes=(_source(), _selection(operation)),
        edges=(
            WorkflowEdge(
                "canonical-source",
                "candidates",
                "select",
                "candidates",
            ),
            WorkflowEdge(
                "canonical-source",
                "scores",
                "select",
                "scores",
            ),
        ),
        contract_lock=(),
        selection_objectives=_objectives(catalog),
    )


def test_catalog_declares_three_multi_objective_nodes_in_selection_package() -> None:
    catalog = _catalog()
    for operation in OPERATIONS:
        node = catalog.require_contract(
            "node_type",
            f"selection.{operation}",
            VERSION,
        )
        binding = catalog.require_contract(
            "binding",
            f"selection.{operation}.direct",
            VERSION,
        )
        method = catalog.require_contract(
            "method",
            f"selection.{operation}.method",
            VERSION,
        )
        assert set(node.descriptor["node_parameters"]) <= {
            "objective_ids",
            "tie_policy",
            "k",
        }
        assert binding.descriptor["selection_objective_consumption"] == {
            "schema_version": VERSION,
            "objective_ids_parameter": "objective_ids",
            "candidate_input_port": "candidates",
            "score_collection_input_port": "scores",
            "candidate_output_port": "candidates",
        }
        assert method.descriptor["scale_contract"] == {
            "kind": "dimensionless-utility-vector"
        }


@pytest.mark.parametrize("operation", OPERATIONS)
def test_compiler_binds_every_explicit_objective_to_exact_node_inputs(
    operation: str,
) -> None:
    catalog = _catalog()
    workflow = _workflow(catalog, operation)

    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_revision=1,
        catalog=catalog,
    )

    assert compiled.execution_plan.selection_objectives == _objectives(catalog)
    contaminated = replace(
        workflow,
        nodes=(
            workflow.nodes[0],
            replace(workflow.nodes[0], node_id="other-source"),
            workflow.nodes[1],
        ),
        selection_objectives=(
            workflow.selection_objectives[0],
            replace(
                workflow.selection_objectives[1],
                score_collection_input=SelectionInput(
                    "other-source",
                    "scores",
                ),
            ),
        ),
    )
    with pytest.raises(
        WorkflowCompileError,
        match="cannot guarantee|Score Collection input does not match",
    ):
        compile_workflow(
            relock_workflow(contaminated, catalog),
            workflow_revision=1,
            catalog=catalog,
        )


def test_canonical_scopes_yield_accepted_weighted_top_three() -> None:
    catalog = _catalog()
    workflow = _workflow(catalog, "weighted_rank")
    plan = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_revision=1,
        catalog=catalog,
    ).execution_plan
    source = catalog.require_factory(
        "contract_test.multi_objective_selection_source.direct",
        VERSION,
    ).build(
        execution_plan=plan,
        frozen_catalog=catalog,
        environment_configuration={},
        run_resources=None,
    )
    values = source.execute(
        inputs={},
        node_parameters={},
        binding_parameters={},
    )
    implementation = catalog.require_factory(
        "selection.weighted_rank.direct",
        VERSION,
    ).build(
        execution_plan=plan,
        frozen_catalog=catalog,
        environment_configuration={},
        run_resources=None,
    )

    selected = implementation.execute(
        inputs={
            "candidates": values["candidates"],
            "scores": values["scores"],
        },
        node_parameters=_selection("weighted_rank").node_parameters,
        binding_parameters={},
    )["candidates"]

    assert [candidate.candidate_id for candidate in selected.items[:3]] == [
        "bravo",
        "charlie",
        "delta",
    ]
    assert selected.items[0] is values["candidates"].items[2]


def test_pareto_and_exact_diversity_method_are_deterministic() -> None:
    catalog = _catalog()
    source_plan = compile_workflow(
        relock_workflow(_workflow(catalog, "pareto"), catalog),
        workflow_revision=1,
        catalog=catalog,
    ).execution_plan
    source = catalog.require_factory(
        "contract_test.multi_objective_selection_source.direct",
        VERSION,
    ).build(
        execution_plan=source_plan,
        frozen_catalog=catalog,
        environment_configuration={},
        run_resources=None,
    )
    values = source.execute(
        inputs={},
        node_parameters={},
        binding_parameters={},
    )

    def execute(operation: str):
        plan = compile_workflow(
            relock_workflow(_workflow(catalog, operation), catalog),
            workflow_revision=1,
            catalog=catalog,
        ).execution_plan
        implementation = catalog.require_factory(
            f"selection.{operation}.direct",
            VERSION,
        ).build(
            execution_plan=plan,
            frozen_catalog=catalog,
            environment_configuration={},
            run_resources=None,
        )
        return implementation.execute(
            inputs={
                "candidates": values["candidates"],
                "scores": values["scores"],
            },
            node_parameters=_selection(operation).node_parameters,
            binding_parameters={},
        )["candidates"]

    pareto = execute("pareto")
    diverse_first = execute("diversity")
    diverse_second = execute("diversity")
    assert [candidate.candidate_id for candidate in pareto.items] == [
        "bravo",
        "charlie",
    ]
    assert [candidate.candidate_id for candidate in diverse_first.items] == [
        "bravo",
        "alpha",
        "charlie",
    ]
    assert diverse_first.items == diverse_second.items
    assert all(
        candidate in values["candidates"].items
        for candidate in diverse_first.items
    )


def test_multi_objective_nodes_reject_implicit_or_incomplete_selection() -> None:
    catalog = _catalog()
    workflow = _workflow(catalog, "weighted_rank")
    missing = replace(
        workflow,
        nodes=(
            workflow.nodes[0],
            replace(
                workflow.nodes[1],
                node_parameters={
                    "objective_ids": ["fixed-3gb1", "absent"],
                    "tie_policy": "candidate_id_ascending",
                },
            ),
        ),
    )
    with pytest.raises(
        WorkflowCompileError,
        match="does not resolve one Workflow Selection Objective",
    ):
        compile_workflow(
            relock_workflow(missing, catalog),
            workflow_revision=1,
            catalog=catalog,
        )

    duplicate = replace(
        workflow,
        nodes=(
            workflow.nodes[0],
            replace(
                workflow.nodes[1],
                node_parameters={
                    "objective_ids": ["fixed-3gb1", "fixed-3gb1"],
                    "tie_policy": "candidate_id_ascending",
                },
            ),
        ),
    )
    with pytest.raises(WorkflowCompileError, match="objective_ids"):
        compile_workflow(
            relock_workflow(duplicate, catalog),
            workflow_revision=1,
            catalog=catalog,
        )


def test_missing_conflicting_and_cross_scope_observations_fail_closed() -> None:
    catalog = _catalog()
    plan = compile_workflow(
        relock_workflow(_workflow(catalog, "weighted_rank"), catalog),
        workflow_revision=1,
        catalog=catalog,
    ).execution_plan
    source = catalog.require_factory(
        "contract_test.multi_objective_selection_source.direct",
        VERSION,
    ).build(
        execution_plan=plan,
        frozen_catalog=catalog,
        environment_configuration={},
        run_resources=None,
    )
    values = source.execute(
        inputs={},
        node_parameters={},
        binding_parameters={},
    )
    implementation = catalog.require_factory(
        "selection.weighted_rank.direct",
        VERSION,
    ).build(
        execution_plan=plan,
        frozen_catalog=catalog,
        environment_configuration={},
        run_resources=None,
    )
    common = {
        "candidates": values["candidates"],
        "scores": values["scores"],
    }

    missing = ScoreCollection(
        "missing-fixed-observation",
        list(values["scores"].entries[1:]),
    )
    with pytest.raises(SelectionError, match="missing observation"):
        implementation.execute(
            inputs={**common, "scores": missing},
            node_parameters=_selection("weighted_rank").node_parameters,
            binding_parameters={},
        )

    conflicting = ScoreCollection(
        "conflicting-fixed-observation",
        [
            *values["scores"].entries,
            replace(values["scores"].entries[0], value=0.99),
        ],
    )
    with pytest.raises(SelectionError, match="conflicting values"):
        implementation.execute(
            inputs={**common, "scores": conflicting},
            node_parameters=_selection("weighted_rank").node_parameters,
            binding_parameters={},
        )

    cross_scope = ScoreCollection(
        "cross-scope-observation",
        [
            values["scores"].entries[0],
            replace(
                values["scores"].entries[1],
                source_partition=FIXED_PARTITION,
            ),
            *values["scores"].entries[2:],
        ],
    )
    with pytest.raises(SelectionError, match="missing observation"):
        implementation.execute(
            inputs={**common, "scores": cross_scope},
            node_parameters=_selection("weighted_rank").node_parameters,
            binding_parameters={},
        )


def test_all_three_nodes_pass_contract_test_kit(tmp_path: Path) -> None:
    catalog = _catalog()
    single_objective_parameters = {
        "filter": {
            "objective_id": "fixed-3gb1",
            "operator": ">=",
            "threshold": 0.5,
            "out_of_scope_policy": "ignore",
            "tie_policy": "candidate_id_ascending",
        },
        "sort": {
            "objective_id": "fixed-3gb1",
            "out_of_scope_policy": "ignore",
            "tie_policy": "candidate_id_ascending",
        },
        "top_k": {
            "objective_id": "fixed-3gb1",
            "k": 2,
            "out_of_scope_policy": "ignore",
            "tie_policy": "candidate_id_ascending",
        },
    }
    cases = tuple(
        ModulePackageContractCase(
            case_id=f"multi-objective-{operation}",
            node_type_id=f"selection.{operation}",
            node_type_version=VERSION,
            binding_id=f"selection.{operation}.direct",
            binding_version=VERSION,
            node_parameters=(
                _selection(operation).node_parameters
                if operation in OPERATIONS
                else single_objective_parameters[operation]
            ),
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token=f"selection-{operation}-v2",
            workflow_nodes=(_source(),),
            workflow_edges=(
                WorkflowEdge(
                    "canonical-source",
                    "candidates",
                    "contract-test-node",
                    "candidates",
                ),
                WorkflowEdge(
                    "canonical-source",
                    "scores",
                    "contract-test-node",
                    "scores",
                ),
            ),
            selection_objectives=_objectives(catalog),
            expected_candidate_counts={
                "candidates": {
                    "filter": 3,
                    "sort": 4,
                    "top_k": 2,
                    "weighted_rank": 4,
                    "pareto": 2,
                    "diversity": 3,
                }[operation],
            },
        )
        for operation in (
            "filter",
            "sort",
            "top_k",
            *OPERATIONS,
        )
    )

    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=cases,
        supporting_registrations=(
            STRUCTURE_COMPARISON_PACKAGE,
            SOURCE_PACKAGE,
        ),
        work_root=tmp_path,
    )

    assert all(case.status == "succeeded" for case in report.case_reports)


def _save_and_compile_public_workflow(
    client: TestClient,
    project_id: str,
    workflow: WorkflowDocument,
) -> tuple[int, str]:
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
    return revision, compiled.json()["compile_id"]


@pytest.mark.parametrize(
    ("operation", "expected_count"),
    (("weighted_rank", 4), ("pareto", 2), ("diversity", 3)),
)
def test_public_selection_uses_the_executed_method_and_is_cache_replay_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expected_count: int,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "explicit multi-objective selection"
    ).id
    workflow = replace(
        _workflow(catalog, operation),
        workflow_id=project_id,
    )

    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        revision, compile_id = _save_and_compile_public_workflow(
            client,
            project_id,
            workflow,
        )

        projections = []
        for request_id in ("multi-objective-first", "multi-objective-replay"):
            started = client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": revision,
                    "compile_id": compile_id,
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
        selection = projection["selection_results"][0]
        assert len(selection["selected_candidate_ids"]) == expected_count
        selected_output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "select"
            and output["output_port"] == "candidates"
        )
        output_ids = [
            item["fields"]["candidate_id"]
            for item in selected_output["values"][0]["fields"]["items"]
        ]
        assert selection["selected_candidate_ids"] == output_ids
        assert selection["selection_node_id"] == "select"
        assert selection["selection_method"]["contract_id"] == (
            f"selection.{operation}.method"
        )
        selected_ids.append(selection["selected_candidate_ids"])
        objective_provenance = selection["objectives"]
        assert [
            (item["declared_weight"], item["effective_weight"])
            for item in objective_provenance
        ] == [(0.7, 0.7), (0.3, 0.3)]
    assert selected_ids[0] == selected_ids[1]
    second_select = next(
        item
        for item in projections[1]["node_dispositions"]
        if item["node_id"] == "select"
    )
    assert second_select["resolution"] == "cache_replayed"


def test_public_run_projects_each_selection_consumer_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "two explicit selection consumers"
    ).id
    weighted = replace(
        _selection("weighted_rank"),
        node_id="select-weighted",
    )
    pareto = replace(
        _selection("pareto"),
        node_id="select-pareto",
    )
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id=project_id,
        nodes=(_source(), weighted, pareto),
        edges=tuple(
            WorkflowEdge(
                "canonical-source",
                source_port,
                node_id,
                target_port,
            )
            for node_id in ("select-weighted", "select-pareto")
            for source_port, target_port in (
                ("candidates", "candidates"),
                ("scores", "scores"),
            )
        ),
        contract_lock=(),
        selection_objectives=_objectives(catalog),
    )

    with TestClient(
        create_app(frozen_catalog_override=catalog)
    ) as client:
        revision, compile_id = _save_and_compile_public_workflow(
            client,
            project_id,
            workflow,
        )
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": revision,
                "compile_id": compile_id,
                "client_request_id": "two-selection-consumers",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert [
        (
            result["selection_node_id"],
            result["selection_method"]["contract_id"],
            len(result["selected_candidate_ids"]),
        )
        for result in projection["selection_results"]
    ] == [
        ("select-weighted", "selection.weighted_rank.method", 4),
        ("select-pareto", "selection.pareto.method", 2),
    ]

    run_id = started.json()["run_id"]
    facts = [
        json.loads(path.read_bytes())
        for path in sorted(
            (
                tmp_path
                / "run"
                / project_id
                / run_id
                / "ledger"
            ).glob("*.json")
        )
    ]

    def reload_facts(candidate_facts: list[dict[str, Any]]) -> None:
        plan_nodes = run_execution_v2._parse_plan_evidence(
            candidate_facts[0]["payload"]["plan_nodes"]
        )
        ledger = run_execution_v2._RunEvidenceLedger(
            ProjectManager(tmp_path / "project"),
            project_id,
            run_id,
            plan_nodes,
        )
        for fact in candidate_facts:
            ledger.load_fact(fact, canonical_json_bytes(fact))

    missing_consumer = [
        deepcopy(fact)
        for fact in facts
        if not (
            fact["fact_type"] == "selection_terminal"
            and fact["payload"].get("result", {}).get("selection_node_id")
            == "select-pareto"
        )
    ]
    for sequence, fact in enumerate(missing_consumer, start=1):
        fact["sequence"] = sequence
    with pytest.raises(run_execution_v2.V2RunError, match="causal"):
        reload_facts(missing_consumer)

    foreign_consumer = deepcopy(facts)
    weighted_terminal = next(
        fact
        for fact in foreign_consumer
        if (
            fact["fact_type"] == "selection_terminal"
            and fact["payload"].get("result", {}).get("selection_node_id")
            == "select-weighted"
        )
    )
    weighted_terminal["payload"]["result"]["selection_node_id"] = (
        "canonical-source"
    )
    with pytest.raises(run_execution_v2.V2RunError, match="causal"):
        reload_facts(foreign_consumer)
