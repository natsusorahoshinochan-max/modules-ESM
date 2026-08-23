"""Ticket 30 acceptance for explicit multi-objective selection."""

from __future__ import annotations

from tests.support.ledger import public_run_events

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.model import (
    CatalogContract,
    FrozenCatalog,
)
from core.catalog.port_contract import (
    PortValueError,
    canonical_json_bytes,
)
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    verify_module_package_contract,
)
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.scoring.selection import (
    ObservationSelector,
    PairwiseContextSelector,
    SelectionError,
    SelectionInput,
    SelectionObjective,
)
from core.project.manager import ProjectManager
from core.parameters.contract import admit_declarations
from tests.support.application import create_application
from protein_workbench_public.workflow_codec import encode_workflow_document
import core.execution.runtime as run_runtime
from core.execution.ledger import FilesystemLedgerStore
from core.workflow.compiler import WorkflowCompileError
from core.workflow.document import WorkflowEdge
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ScoreCollection,
)
from tests.support.catalog import catalog_contract, install_runtime
from modules.selection.package import MODULE_PACKAGE
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from tests.fixtures.multi_objective_selection_sources.package import (
    FIXED_PARTITION,
    NORMALIZATION,
    PAIRED_PARTITION,
    MODULE_PACKAGE as SOURCE_PACKAGE,
)
from tests.fixtures.public_v2 import (
    retrieve_typed_output_values,
    wait_for_testclient_run_terminal,
)
from tests.fixtures.scientific_operation import build_operation, operation_call


WORKFLOW_SCHEMA_VERSION = "2.1.0"
SOURCE_METHOD_VERSION = "2.1.0"
SELECTION_METHOD_VERSION = "4.0.0"
NODE_BINDING_VERSION = "5.0.0"
SOURCE_NODE_BINDING_VERSION = "4.0.0"
SCORER_NODE_BINDING_VERSION = "5.0.0"
METRIC_UTILITY_VERSION = "3.0.0"
OPERATIONS = ("weighted_rank", "pareto", "diversity")


def _catalog():
    return build_frozen_catalog(
        (
            MODULE_PACKAGE,
            STRUCTURE_COMPARISON_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
            SOURCE_PACKAGE,
        )
    )


def _catalog_with_default_selection_parameter(
    operation: str,
    parameter_name: str,
    default: object,
) -> FrozenCatalog:
    base = _catalog()
    node_id = f"selection.{operation}"
    binding_id = f"selection.{operation}.direct"
    original_node = base.require_contract(
        "node_type",
        node_id,
        NODE_BINDING_VERSION,
    )
    node_descriptor = json.loads(canonical_json_bytes(original_node.descriptor))
    parameter = node_descriptor["node_parameters"][parameter_name]
    parameter.pop("required", None)
    parameter["default"] = default
    node = catalog_contract(
        "node_type",
        node_id,
        NODE_BINDING_VERSION,
        node_descriptor,
    )
    original_binding = base.require_contract(
        "binding",
        binding_id,
        NODE_BINDING_VERSION,
    )
    binding_descriptor = json.loads(
        canonical_json_bytes(original_binding.descriptor)
    )
    binding_descriptor["node_type"] = node.reference()
    binding = catalog_contract(
        "binding",
        binding_id,
        NODE_BINDING_VERSION,
        binding_descriptor,
    )
    contracts = tuple(
        node
        if (
            contract.contract_kind,
            contract.contract_id,
        )
        == ("node_type", node_id)
        else binding
        if (
            contract.contract_kind,
            contract.contract_id,
        )
        == ("binding", binding_id)
        else contract
        for contract in base.contracts
    )
    binding_reference = ExactContractReference(**binding.reference())
    availability = tuple(
        replace(snapshot, binding=binding_reference)
        if snapshot.binding.contract_id == binding_id
        else snapshot
        for snapshot in base.availability
    )
    return FrozenCatalog(
        base.port_types,
        contracts=install_runtime(
            contracts,
            factories={
                (binding_id, NODE_BINDING_VERSION): (
                    original_binding.definition.factory
                )
            },
            readiness={
                (binding_id, NODE_BINDING_VERSION): (
                    original_binding.definition.readiness
                )
            },
            randomness=(
                {
                    (binding_id, NODE_BINDING_VERSION): (
                        original_binding.definition.effective_randomness_resolver
                    )
                }
                if original_binding.definition.effective_randomness_resolver
                is not None
                else {}
            ),
        ),
        availability=availability,
        availability_observed_at=base.availability_observed_at,
    )


def _reference(catalog, kind: str, contract_id: str) -> ExactContractReference:
    version = (
        SOURCE_METHOD_VERSION
        if kind == "method"
        else METRIC_UTILITY_VERSION
    )
    return ExactContractReference(
        **catalog.require_contract(kind, contract_id, version).reference()
    )


def _source() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="canonical-source",
        node_type_id="contract_test.multi_objective_selection_source",
        node_type_version=SOURCE_NODE_BINDING_VERSION,
        binding_id="contract_test.multi_objective_selection_source.direct",
        binding_version=SOURCE_NODE_BINDING_VERSION,
        node_parameters={},
        binding_parameters={},
    )


def _scorer() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="canonical-scores",
        node_type_id="contract_test.multi_objective_selection_scores",
        node_type_version=SCORER_NODE_BINDING_VERSION,
        binding_id="contract_test.multi_objective_selection_scores.direct",
        binding_version=SCORER_NODE_BINDING_VERSION,
        node_parameters={},
        binding_parameters={},
    )


def _scorer_edges() -> tuple[WorkflowEdge, ...]:
    return tuple(
        WorkflowEdge(
            "canonical-source",
            port,
            "canonical-scores",
            port,
        )
        for port in ("candidates", "references", "pairing")
    )


def _selection_edges(node_id: str = "select") -> tuple[WorkflowEdge, ...]:
    return (
        WorkflowEdge(
            "canonical-source",
            "candidates",
            node_id,
            "candidates",
        ),
        WorkflowEdge(
            "canonical-scores",
            "scores",
            node_id,
            "scores",
        ),
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
        node_type_version=NODE_BINDING_VERSION,
        binding_id=f"selection.{operation}.direct",
        binding_version=NODE_BINDING_VERSION,
        node_parameters=parameters,
        binding_parameters={},
    )


def _objectives(catalog) -> tuple[SelectionObjective, SelectionObjective]:
    candidate_input = SelectionInput("canonical-source", "candidates")
    score_input = SelectionInput("canonical-scores", "scores")
    common = {
        "candidate_input": candidate_input,
        "score_collection_input": score_input,
        "metric": _reference(
            catalog,
            "metric",
            "contract_test.multi_objective_selection_score",
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
                "contract_test.multi_objective_selection_score."
                "fixed_3gb1.identity",
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
                "contract_test.multi_objective_selection_score."
                "paired_esm3.identity",
            ),
            weight=0.3,
            source_partition=PAIRED_PARTITION,
            **common,
        ),
    )


def _selectors(catalog) -> tuple[ObservationSelector, ...]:
    objective = _objectives(catalog)[0]
    return (
        ObservationSelector(
            selector_id="fixed-3gb1-raw",
            candidate_input=objective.candidate_input,
            score_collection_input=objective.score_collection_input,
            metric=objective.metric,
            method=objective.method,
            context_selector=objective.context_selector,
            source_partition=objective.source_partition,
        ),
    )


def _workflow(catalog, operation: str) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id=f"multi-objective-{operation}",
        nodes=(_source(), _scorer(), _selection(operation)),
        edges=(*_scorer_edges(), *_selection_edges()),
        contract_lock=(),
        selection_objectives=_objectives(catalog),
    )


def _direct_fixture_values(catalog) -> dict[str, Any]:
    source = build_operation(
        catalog,
        "contract_test.multi_objective_selection_source.direct",
        None,
        binding_version=SOURCE_NODE_BINDING_VERSION,
    )
    source_values = source.execute(operation_call())
    structure_port = catalog.require_port_type(
        "protein.structure",
        "4.0.0",
    )
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in source_values["candidates"].items
    }
    references_by_id = {
        candidate.candidate_id: candidate
        for candidate in source_values["references"].items
    }
    pairing = PairwiseCandidateMapping(
        tuple(
            PairwiseCandidateMatch(
                subject=CandidateDataReference(
                    candidate_id=entry.subject_candidate_id,
                    data_type_id="protein.structure",
                    content_digest=structure_port.content_digest(
                        candidates_by_id[entry.subject_candidate_id].data
                    ),
                ),
                reference=CandidateDataReference(
                    candidate_id=entry.reference_candidate_id,
                    data_type_id="protein.structure",
                    content_digest=structure_port.content_digest(
                        references_by_id[entry.reference_candidate_id].data
                    ),
                ),
            )
            for entry in source_values["pairing"].entries
        )
    )
    scorer = build_operation(
        catalog,
        "contract_test.multi_objective_selection_scores.direct",
        None,
        binding_version=SCORER_NODE_BINDING_VERSION,
    )
    scorer_values = scorer.execute(operation_call(
        catalog=catalog,
        binding_id="contract_test.multi_objective_selection_scores.direct",
        binding_version=SCORER_NODE_BINDING_VERSION,
        inputs={
            "candidates": source_values["candidates"],
            "references": source_values["references"],
            "pairing": pairing,
        },
        node_parameters={},
        binding_parameters={},
    ))
    return {
        **source_values,
        "pairing": pairing,
        **scorer_values,
    }


def test_catalog_declares_three_multi_objective_nodes_in_selection_package() -> None:
    catalog = _catalog()
    for operation in OPERATIONS:
        node = catalog.require_contract(
            "node_type",
            f"selection.{operation}",
            NODE_BINDING_VERSION,
        )
        binding = catalog.require_contract(
            "binding",
            f"selection.{operation}.direct",
            NODE_BINDING_VERSION,
        )
        method = catalog.require_contract(
            "method",
            f"selection.{operation}.method",
            SELECTION_METHOD_VERSION,
        )
        assert set(node.descriptor["node_parameters"]) <= {
            "objective_ids",
            "tie_policy",
            "k",
        }
        assert binding.descriptor["selection_objective_consumption"] == {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "objective_ids_parameter": "objective_ids",
            "candidate_input_port": "candidates",
            "score_collection_input_port": "scores",
            "candidate_output_port": "candidates",
        }
        assert method.descriptor["scale_contract"] == {
            "kind": "dimensionless-utility-vector"
        }


def test_fixture_scores_only_already_admitted_candidate_data_references() -> None:
    catalog = _catalog()
    source = catalog.require_contract(
        "node_type",
        "contract_test.multi_objective_selection_source",
        SOURCE_NODE_BINDING_VERSION,
    )
    scorer = catalog.require_contract(
        "node_type",
        "contract_test.multi_objective_selection_scores",
        SCORER_NODE_BINDING_VERSION,
    )
    binding = catalog.require_contract(
        "binding",
        "contract_test.multi_objective_selection_scores.direct",
        SCORER_NODE_BINDING_VERSION,
    )

    assert {
        output["name"] for output in source.descriptor["outputs"]
    } == {"candidates", "references", "pairing"}
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in scorer.descriptor["inputs"]
    ] == [
        ("candidates", "candidate.collection", "4.0.0"),
        ("references", "candidate.collection", "4.0.0"),
        ("pairing", "candidate.pairing", "4.0.0"),
    ]
    assert [
        (
            output["name"],
            output["port_type"]["contract_id"],
            output["port_type"]["contract_version"],
        )
        for output in scorer.descriptor["outputs"]
    ] == [("scores", "score.collection", "5.0.0")]
    assert all(
        declaration["subject_direction"] == "input"
        and declaration["reference_direction"] == "input"
        for declaration in binding.descriptor["produced_observations"]
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_compiler_binds_every_explicit_objective_to_exact_node_inputs(
    operation: str,
) -> None:
    catalog = _catalog()
    workflow = _workflow(catalog, operation)

    compiled = compile(
                   CompilationRequest(
                       lock_workflow(workflow, catalog),
                       1,
                   ),
                   catalog,
               )

    assert compiled.selection_objectives == _objectives(catalog)
    contaminated = replace(
        workflow,
        nodes=(
            *workflow.nodes[:2],
            replace(workflow.nodes[1], node_id="other-scores"),
            workflow.nodes[2],
        ),
        edges=(
            *workflow.edges,
            *tuple(
                replace(edge, target_node_id="other-scores")
                for edge in _scorer_edges()
            ),
        ),
        selection_objectives=(
            workflow.selection_objectives[0],
            replace(
                workflow.selection_objectives[1],
                score_collection_input=SelectionInput(
                    "other-scores",
                    "scores",
                ),
            ),
        ),
    )
    with pytest.raises(
        WorkflowCompileError,
        match="cannot guarantee|Score Collection input does not match",
    ):
        compile(
            CompilationRequest(
                lock_workflow(contaminated, catalog),
                1,
            ),
            catalog,
        )


def test_compiler_rejects_selection_objective_without_explicit_consumer(
) -> None:
    catalog = _catalog()
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id="unconsumed-objective",
        nodes=(_source(), _scorer()),
        edges=_scorer_edges(),
        contract_lock=(),
        selection_objectives=(_objectives(catalog)[0],),
    )

    with pytest.raises(WorkflowCompileError) as raised:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert raised.value.code == "unconsumed_selection_objective"
    assert raised.value.field_path == ("selection_objectives", 0)


def test_compiler_rejects_observation_selector_without_explicit_consumer(
) -> None:
    catalog = _catalog()
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id="unconsumed-selector",
        nodes=(_source(), _scorer()),
        edges=_scorer_edges(),
        contract_lock=(),
        observation_selectors=_selectors(catalog),
    )

    with pytest.raises(WorkflowCompileError) as raised:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert raised.value.code == "unconsumed_observation_selector"
    assert raised.value.field_path == ("observation_selectors", 0)


def test_compiler_rejects_observation_selector_with_multiple_consumers(
) -> None:
    catalog = _catalog()
    filters = tuple(
        WorkflowNodeInstance(
            node_id=node_id,
            node_type_id="selection.filter",
            node_type_version=NODE_BINDING_VERSION,
            binding_id="selection.filter.direct",
            binding_version=NODE_BINDING_VERSION,
            node_parameters={
                "selector_id": "fixed-3gb1-raw",
                "operator": ">=",
                "threshold": threshold,
                "out_of_scope_policy": "ignore",
                "tie_policy": "candidate_id_ascending",
            },
            binding_parameters={},
        )
        for node_id, threshold in (
            ("filter-low", 0.5),
            ("filter-high", 0.8),
        )
    )
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id="multiply-consumed-selector",
        nodes=(_source(), _scorer(), *filters),
        edges=(
            *_scorer_edges(),
            *_selection_edges("filter-low"),
            *_selection_edges("filter-high"),
        ),
        contract_lock=(),
        observation_selectors=_selectors(catalog),
    )

    with pytest.raises(WorkflowCompileError) as raised:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert raised.value.code == "multiple_observation_selector_consumers"
    assert raised.value.field_path == ("observation_selectors", 0)


def test_compiler_rejects_each_unconsumed_objective_in_mixed_workflow(
) -> None:
    catalog = _catalog()
    selection = WorkflowNodeInstance(
        node_id="select",
        node_type_id="selection.sort",
        node_type_version=NODE_BINDING_VERSION,
        binding_id="selection.sort.direct",
        binding_version=NODE_BINDING_VERSION,
        node_parameters={
            "objective_id": "fixed-3gb1",
            "tie_policy": "candidate_id_ascending",
            "out_of_scope_policy": "error",
        },
        binding_parameters={},
    )
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id="partially-consumed-objectives",
        nodes=(_source(), _scorer(), selection),
        edges=(*_scorer_edges(), *_selection_edges()),
        contract_lock=(),
        selection_objectives=_objectives(catalog),
    )

    with pytest.raises(WorkflowCompileError) as raised:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert raised.value.code == "unconsumed_selection_objective"
    assert raised.value.field_path == ("selection_objectives", 1)


@pytest.mark.parametrize(
    ("operation", "parameter_name", "default"),
    (
        ("sort", "objective_id", "fixed-3gb1"),
        (
            "weighted_rank",
            "objective_ids",
            ["fixed-3gb1", "paired-esm3"],
        ),
        ("filter", "selector_id", "fixed-3gb1-raw"),
    ),
)
def test_compiler_resolves_selection_consumers_from_normalized_defaults(
    operation: str,
    parameter_name: str,
    default: object,
) -> None:
    catalog = _catalog_with_default_selection_parameter(
        operation,
        parameter_name,
        default,
    )
    node_parameters: dict[str, object]
    if operation == "filter":
        node_parameters = {
            "operator": ">=",
            "threshold": 0.5,
        }
    else:
        node_parameters = {}
    selection_node = WorkflowNodeInstance(
        node_id="select",
        node_type_id=f"selection.{operation}",
        node_type_version=NODE_BINDING_VERSION,
        binding_id=f"selection.{operation}.direct",
        binding_version=NODE_BINDING_VERSION,
        node_parameters=node_parameters,
        binding_parameters={},
    )
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id=f"defaulted-{operation}",
        nodes=(_source(), _scorer(), selection_node),
        edges=(*_scorer_edges(), *_selection_edges()),
        contract_lock=(),
        observation_selectors=(
            _selectors(catalog) if operation == "filter" else ()
        ),
        selection_objectives=(
            ()
            if operation == "filter"
            else _objectives(catalog)
            if operation == "weighted_rank"
            else (_objectives(catalog)[0],)
        ),
    )

    compiled = compile(
                   CompilationRequest(
                       lock_workflow(workflow, catalog),
                       1,
                   ),
                   catalog,
               )

    plan_node = next(
        node
        for node in compiled.nodes
        if node.node_id == "select"
    )
    expected = tuple(default) if isinstance(default, list) else default
    assert plan_node.node_parameters[parameter_name] == expected
    if operation == "filter":
        assert [
            item.selector_id
            for item in plan_node._runtime.observation_selectors
        ] == ["fixed-3gb1-raw"]
    else:
        expected_objective_ids = (
            tuple(default) if isinstance(default, list) else (default,)
        )
        assert tuple(
            item.objective_id
            for item in plan_node._runtime.selection_objectives
        ) == expected_objective_ids


def test_canonical_scopes_yield_accepted_weighted_top_three() -> None:
    catalog = _catalog()
    workflow = _workflow(catalog, "weighted_rank")
    plan = compile(
               CompilationRequest(
                   lock_workflow(workflow, catalog),
                   1,
               ),
               catalog,
           )
    values = _direct_fixture_values(catalog)
    implementation = build_operation(
        catalog,
        "selection.weighted_rank.direct",
        None,
        binding_version=NODE_BINDING_VERSION,
        selection_objectives=plan.selection_objectives,
        observation_selectors=plan.observation_selectors,
    )

    call = operation_call(
        catalog=catalog,
        binding_id="selection.weighted_rank.direct",
        binding_version=NODE_BINDING_VERSION,
        inputs={
            "candidates": values["candidates"],
            "scores": values["scores"],
        },
        node_parameters=_selection("weighted_rank").node_parameters,
        binding_parameters={},
    )
    selected = implementation.execute(call)["candidates"]

    assert [candidate.candidate_id for candidate in selected.items[:3]] == [
        "bravo",
        "charlie",
        "delta",
    ]
    assert selected.items[0] is call.inputs["candidates"].value.items[2]


def test_pareto_and_exact_diversity_method_are_deterministic() -> None:
    catalog = _catalog()
    values = _direct_fixture_values(catalog)

    def execute(operation: str):
        plan = compile(
                   CompilationRequest(
                       lock_workflow(_workflow(catalog, operation), catalog),
                       1,
                   ),
                   catalog,
               )
        implementation = build_operation(
            catalog,
            f"selection.{operation}.direct",
            None,
            binding_version=NODE_BINDING_VERSION,
            selection_objectives=plan.selection_objectives,
            observation_selectors=plan.observation_selectors,
        )
        return implementation.execute(operation_call(
            catalog=catalog,
            binding_id=f"selection.{operation}.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={
                "candidates": values["candidates"],
                "scores": values["scores"],
            },
            node_parameters=_selection(operation).node_parameters,
            binding_parameters={},
        ))["candidates"]

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
            *workflow.nodes[:2],
            replace(
                workflow.nodes[2],
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
    ) as captured:
        compile(
            CompilationRequest(
                lock_workflow(missing, catalog),
                1,
            ),
            catalog,
        )
    assert captured.value.field_path == (
        "nodes",
        2,
        "node_parameters",
        "objective_ids",
    )
    assert captured.value.node_id == "select"

    duplicate = replace(
        workflow,
        nodes=(
            *workflow.nodes[:2],
            replace(
                workflow.nodes[2],
                node_parameters={
                    "objective_ids": ["fixed-3gb1", "fixed-3gb1"],
                    "tie_policy": "candidate_id_ascending",
                },
            ),
        ),
    )
    with pytest.raises(WorkflowCompileError, match="objective_ids"):
        compile(
            CompilationRequest(
                lock_workflow(duplicate, catalog),
                1,
            ),
            catalog,
        )


@pytest.mark.parametrize(
    ("operation", "parameter_name"),
    (("sort", "objective_id"), ("filter", "selector_id")),
)
def test_scalar_selection_consumer_error_uses_the_node_parameter_path(
    operation: str,
    parameter_name: str,
) -> None:
    catalog = _catalog()
    selection_parameters = (
        {
            "objective_id": "absent-objective",
            "out_of_scope_policy": "error",
            "tie_policy": "candidate_id_ascending",
        }
        if operation == "sort"
        else {
            "selector_id": "absent-selector",
            "operator": ">=",
            "threshold": 0.5,
            "out_of_scope_policy": "error",
            "tie_policy": "candidate_id_ascending",
        }
    )
    selection = WorkflowNodeInstance(
        node_id="selection-node-with-text-id",
        node_type_id=f"selection.{operation}",
        node_type_version=NODE_BINDING_VERSION,
        binding_id=f"selection.{operation}.direct",
        binding_version=NODE_BINDING_VERSION,
        node_parameters=selection_parameters,
        binding_parameters={},
    )
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id=f"missing-{operation}-selection",
        nodes=(_source(), _scorer(), selection),
        edges=(
            *_scorer_edges(),
            *_selection_edges("selection-node-with-text-id"),
        ),
        contract_lock=(),
        selection_objectives=(
            _objectives(catalog) if operation == "sort" else ()
        ),
        observation_selectors=(
            _selectors(catalog) if operation == "filter" else ()
        ),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert captured.value.field_path == (
        "nodes",
        2,
        "node_parameters",
        parameter_name,
    )
    assert captured.value.node_id == "selection-node-with-text-id"


@pytest.mark.parametrize("selection_kind", ("objective", "selector"))
@pytest.mark.parametrize(
    ("mismatched_port", "expected_edge_index"),
    (("candidates", 6), ("scores", 7)),
)
def test_selection_source_mismatch_points_to_the_implicated_edge(
    selection_kind: str,
    mismatched_port: str,
    expected_edge_index: int,
) -> None:
    catalog = _catalog()
    other_source = replace(_source(), node_id="other-source")
    other_scorer = replace(_scorer(), node_id="other-scores")
    selection_node_id = "selection-node-with-text-id"
    if selection_kind == "objective":
        selection = WorkflowNodeInstance(
            node_id=selection_node_id,
            node_type_id="selection.sort",
            node_type_version=NODE_BINDING_VERSION,
            binding_id="selection.sort.direct",
            binding_version=NODE_BINDING_VERSION,
            node_parameters={
                "objective_id": "fixed-3gb1",
                "out_of_scope_policy": "error",
                "tie_policy": "candidate_id_ascending",
            },
            binding_parameters={},
        )
    else:
        selection = WorkflowNodeInstance(
            node_id=selection_node_id,
            node_type_id="selection.filter",
            node_type_version=NODE_BINDING_VERSION,
            binding_id="selection.filter.direct",
            binding_version=NODE_BINDING_VERSION,
            node_parameters={
                "selector_id": "fixed-3gb1-raw",
                "operator": ">=",
                "threshold": 0.5,
                "out_of_scope_policy": "error",
                "tie_policy": "candidate_id_ascending",
            },
            binding_parameters={},
        )
    objective = replace(
        _objectives(catalog)[0],
        candidate_input=SelectionInput("other-source", "candidates"),
        score_collection_input=SelectionInput("other-scores", "scores"),
    )
    selector = replace(
        _selectors(catalog)[0],
        candidate_input=SelectionInput("other-source", "candidates"),
        score_collection_input=SelectionInput("other-scores", "scores"),
    )
    other_scorer_edges = tuple(
        replace(
            edge,
            source_node_id="other-source",
            target_node_id="other-scores",
        )
        for edge in _scorer_edges()
    )
    candidate_source = (
        "canonical-source"
        if mismatched_port == "candidates"
        else "other-source"
    )
    score_source = (
        "canonical-scores"
        if mismatched_port == "scores"
        else "other-scores"
    )
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id=f"mismatched-{selection_kind}-{mismatched_port}",
        nodes=(
            _source(),
            _scorer(),
            other_source,
            other_scorer,
            selection,
        ),
        edges=(
            *_scorer_edges(),
            *other_scorer_edges,
            WorkflowEdge(
                candidate_source,
                "candidates",
                selection_node_id,
                "candidates",
            ),
            WorkflowEdge(
                score_source,
                "scores",
                selection_node_id,
                "scores",
            ),
        ),
        contract_lock=(),
        selection_objectives=(
            (objective,) if selection_kind == "objective" else ()
        ),
        observation_selectors=(
            (selector,) if selection_kind == "selector" else ()
        ),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert captured.value.code == "unsatisfied_selector"
    assert captured.value.field_path == (
        "edges",
        expected_edge_index,
        "source_node_id",
    )
    assert captured.value.node_id == selection_node_id


def test_missing_conflicting_and_cross_scope_observations_fail_closed() -> None:
    catalog = _catalog()
    plan = compile(
               CompilationRequest(
                   lock_workflow(_workflow(catalog, 'weighted_rank'), catalog),
                   1,
               ),
               catalog,
           )
    values = _direct_fixture_values(catalog)
    implementation = build_operation(
        catalog,
        "selection.weighted_rank.direct",
        None,
        binding_version=NODE_BINDING_VERSION,
        selection_objectives=plan.selection_objectives,
        observation_selectors=plan.observation_selectors,
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
        implementation.execute(operation_call(
            catalog=catalog,
            binding_id="selection.weighted_rank.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={**common, "scores": missing},
            node_parameters=_selection("weighted_rank").node_parameters,
            binding_parameters={},
        ))

    conflicting = ScoreCollection(
        "conflicting-fixed-observation",
        [
            *values["scores"].entries,
            replace(values["scores"].entries[0], value=0.99),
        ],
    )
    with pytest.raises(PortValueError, match="conflicting values"):
        implementation.execute(operation_call(
            catalog=catalog,
            binding_id="selection.weighted_rank.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={**common, "scores": conflicting},
            node_parameters=_selection("weighted_rank").node_parameters,
            binding_parameters={},
        ))

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
        implementation.execute(operation_call(
            catalog=catalog,
            binding_id="selection.weighted_rank.direct",
            binding_version=NODE_BINDING_VERSION,
            inputs={**common, "scores": cross_scope},
            node_parameters=_selection("weighted_rank").node_parameters,
            binding_parameters={},
        ))


def test_all_three_nodes_pass_contract_test_kit(tmp_path: Path) -> None:
    catalog = _catalog()
    single_objective_parameters = {
        "filter": {
            "selector_id": "fixed-3gb1-raw",
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
            node_type_version=NODE_BINDING_VERSION,
            binding_id=f"selection.{operation}.direct",
            binding_version=NODE_BINDING_VERSION,
            node_parameters=(
                _selection(operation).node_parameters
                if operation in OPERATIONS
                else single_objective_parameters[operation]
            ),
            binding_parameters={},
            environment_values={},
            workflow_nodes=(_source(), _scorer()),
            workflow_edges=(
                *_scorer_edges(),
                *_selection_edges("contract-test-node"),
            ),
            selection_objectives=(
                ()
                if operation == "filter"
                else _objectives(catalog)
                if operation in OPERATIONS
                else (_objectives(catalog)[0],)
            ),
            observation_selectors=(
                _selectors(catalog) if operation == "filter" else ()
            ),
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
            STRUCTURE_TRANSFORM_PACKAGE,
            SOURCE_PACKAGE,
        ),
        work_root=tmp_path,
    )

    assert all(case.status == "succeeded" for case in report.case_reports)


def _commit_public_workflow(
    client: TestClient,
    project_id: str,
    workflow: WorkflowDocument,
) -> dict[str, Any]:
    committed = client.post(
        f"/api/v2/projects/{project_id}/workflow:commit",
        json={
            "workflow": encode_workflow_document(workflow),
        },
    )
    assert committed.status_code == 200
    return committed.json()


def _run_public_workflow(
    client: TestClient,
    project_id: str,
    *,
    workflow_commit_id: str,
    request_id: str,
) -> dict[str, Any]:
    started = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_commit_id": workflow_commit_id,
            "client_request_id": request_id,
        },
    )
    assert started.status_code == 202
    return wait_for_testclient_run_terminal(
        client,
        project_id,
        started.json()["run_id"],
    )


def _selection_public_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_name: str,
) -> tuple[Any, str, WorkflowDocument, dict[str, Path]]:
    catalog = _catalog()
    roots: dict[str, Path] = {}
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        roots[name] = root
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(project_name).id
    workflow = replace(
        _workflow(catalog, "weighted_rank"),
        workflow_id=project_id,
    )
    return catalog, project_id, workflow, roots


class _FailRunClosureStore:
    def __init__(self) -> None:
        self.filesystem = FilesystemLedgerStore()

    def read_transactions(self, *, root, relative_parts):
        return self.filesystem.read_transactions(
            root=root,
            relative_parts=relative_parts,
        )

    def publish(self, *, root, relative_parts, payload) -> None:
        transaction = json.loads(payload)
        if any(
            fact["fact_type"] == "run_terminal"
            for fact in transaction["facts"]
        ):
            raise OSError("fixture Run Closure failure")
        self.filesystem.publish(
            root=root,
            relative_parts=relative_parts,
            payload=payload,
        )


def test_result_identity_ignores_node_renames_while_plan_digest_tracks_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "result identity ignores workflow locators"
    ).id
    original = replace(
        _workflow(catalog, "weighted_rank"),
        workflow_id=project_id,
    )
    renamed = replace(
        original,
        nodes=(
            replace(original.nodes[0], node_id="renamed-source"),
            replace(original.nodes[1], node_id="renamed-scores"),
            replace(original.nodes[2], node_id="renamed-select"),
        ),
        edges=tuple(
            replace(
                edge,
                source_node_id={
                    "canonical-source": "renamed-source",
                    "canonical-scores": "renamed-scores",
                }.get(edge.source_node_id, edge.source_node_id),
                target_node_id={
                    "canonical-scores": "renamed-scores",
                    "select": "renamed-select",
                }.get(edge.target_node_id, edge.target_node_id),
            )
            for edge in original.edges
        ),
        selection_objectives=tuple(
            replace(
                objective,
                candidate_input=SelectionInput(
                    "renamed-source",
                    objective.candidate_input.output_port,
                ),
                score_collection_input=SelectionInput(
                    "renamed-scores",
                    objective.score_collection_input.output_port,
                ),
            )
            for objective in original.selection_objectives
        ),
    )

    with TestClient(create_application(frozen_catalog_override=catalog)) as client:
        first_committed = _commit_public_workflow(
            client,
            project_id,
            original,
        )
        first = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=first_committed["workflow_commit_id"],
            request_id="identity-before-rename",
        )
        second_committed = _commit_public_workflow(
            client,
            project_id,
            renamed,
        )
        second = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=second_committed["workflow_commit_id"],
            request_id="identity-after-rename",
        )

    assert (
        first_committed["execution_plan_digest"]
        != second_committed["execution_plan_digest"]
    )
    first_identities = {
        output["node_id"]: output["result_identity"]
        for output in first["outputs"]
        if output["output_port"] == "candidates"
    }
    second_identities = {
        output["node_id"]: output["result_identity"]
        for output in second["outputs"]
        if output["output_port"] == "candidates"
    }
    assert second_identities == {
        "renamed-source": first_identities["canonical-source"],
        "renamed-select": first_identities["select"],
    }
    assert {
        item["node_id"]: item["resolution"]
        for item in second["node_dispositions"]
    } == {
        "renamed-source": "cache_replayed",
        "renamed-scores": "cache_replayed",
        "renamed-select": "cache_replayed",
    }


def test_selection_result_identity_ignores_objective_label_renames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "result identity ignores objective labels"
    ).id
    original = replace(
        _workflow(catalog, "weighted_rank"),
        workflow_id=project_id,
    )
    renamed_objective_ids = tuple(
        f"renamed-{objective.objective_id}"
        for objective in original.selection_objectives
    )
    renamed = replace(
        original,
        nodes=(
            *original.nodes[:2],
            replace(
                original.nodes[2],
                node_parameters={
                    **dict(original.nodes[1].node_parameters),
                    "objective_ids": list(renamed_objective_ids),
                },
            ),
        ),
        selection_objectives=tuple(
            replace(objective, objective_id=renamed_id)
            for objective, renamed_id in zip(
                original.selection_objectives,
                renamed_objective_ids,
                strict=True,
            )
        ),
    )

    with TestClient(create_application(frozen_catalog_override=catalog)) as client:
        first_committed = _commit_public_workflow(
            client,
            project_id,
            original,
        )
        first = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=first_committed["workflow_commit_id"],
            request_id="objective-label-before-rename",
        )
        second_committed = _commit_public_workflow(
            client,
            project_id,
            renamed,
        )
        second = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=second_committed["workflow_commit_id"],
            request_id="objective-label-after-rename",
        )

    assert (
        first_committed["execution_plan_digest"]
        != second_committed["execution_plan_digest"]
    )
    first_selection_output = next(
        output
        for output in first["outputs"]
        if output["node_id"] == "select"
        and output["output_port"] == "candidates"
    )
    second_selection_output = next(
        output
        for output in second["outputs"]
        if output["node_id"] == "select"
        and output["output_port"] == "candidates"
    )
    assert (
        first_selection_output["result_identity"]
        == second_selection_output["result_identity"]
    )
    assert next(
        disposition
        for disposition in second["node_dispositions"]
        if disposition["node_id"] == "select"
    )["resolution"] == "cache_replayed"
    assert [
        objective["objective_id"]
        for objective in second["selection_results"][0]["objectives"]
    ] == list(renamed_objective_ids)


def test_consumed_objective_weight_invalidates_only_the_selection_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "consumed objective weight identity"
    ).id
    original = replace(
        _workflow(catalog, "weighted_rank"),
        workflow_id=project_id,
    )
    reweighted = replace(
        original,
        selection_objectives=tuple(
            replace(objective, weight=weight)
            for objective, weight in zip(
                original.selection_objectives,
                (0.6, 0.4),
                strict=True,
            )
        ),
    )

    with TestClient(create_application(frozen_catalog_override=catalog)) as client:
        first_committed = _commit_public_workflow(
            client,
            project_id,
            original,
        )
        first = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=first_committed["workflow_commit_id"],
            request_id="objective-weight-before",
        )
        second_committed = _commit_public_workflow(
            client,
            project_id,
            reweighted,
        )
        second = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=second_committed["workflow_commit_id"],
            request_id="objective-weight-after",
        )

    def result_identity(projection: dict[str, Any], node_id: str) -> str:
        return next(
            output["result_identity"]
            for output in projection["outputs"]
            if output["node_id"] == node_id
            and output["output_port"] == "candidates"
        )

    assert result_identity(first, "canonical-source") == result_identity(
        second,
        "canonical-source",
    )
    assert result_identity(first, "select") != result_identity(
        second,
        "select",
    )
    assert {
        item["node_id"]: item["resolution"]
        for item in second["node_dispositions"]
        } == {
            "canonical-source": "cache_replayed",
            "canonical-scores": "cache_replayed",
            "select": "executed",
        }


def test_upstream_result_identity_ignores_unrelated_downstream_utility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "unrelated Utility isolation"
    ).id
    source_only = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id=project_id,
        nodes=(_source(),),
        edges=(),
        contract_lock=(),
    )
    with_selection = replace(
        _workflow(catalog, "weighted_rank"),
        workflow_id=project_id,
    )

    with TestClient(create_application(frozen_catalog_override=catalog)) as client:
        first_committed = _commit_public_workflow(
            client,
            project_id,
            source_only,
        )
        first = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=first_committed["workflow_commit_id"],
            request_id="identity-without-downstream-utility",
        )
        second_committed = _commit_public_workflow(
            client,
            project_id,
            with_selection,
        )
        second = _run_public_workflow(
            client,
            project_id,
            workflow_commit_id=second_committed["workflow_commit_id"],
            request_id="identity-with-downstream-utility",
        )

    first_source = next(
        output
        for output in first["outputs"]
        if output["node_id"] == "canonical-source"
        and output["output_port"] == "candidates"
    )
    second_source = next(
        output
        for output in second["outputs"]
        if output["node_id"] == "canonical-source"
        and output["output_port"] == "candidates"
    )
    assert first_source["result_identity"] == second_source["result_identity"]
    source_disposition = next(
        item
        for item in second["node_dispositions"]
        if item["node_id"] == "canonical-source"
    )
    assert source_disposition["resolution"] == "cache_replayed"


def test_resolved_plan_executes_observations_objectives_and_selectors_without_catalog_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    project_id = ProjectManager(tmp_path / "project").create(
        "compile-resolved selection facts"
    ).id
    filter_node = WorkflowNodeInstance(
        node_id="filter",
        node_type_id="selection.filter",
        node_type_version=NODE_BINDING_VERSION,
        binding_id="selection.filter.direct",
        binding_version=NODE_BINDING_VERSION,
        node_parameters={
            "selector_id": "fixed-3gb1-raw",
            "operator": ">=",
            "threshold": 0.5,
            "out_of_scope_policy": "ignore",
            "tie_policy": "candidate_id_ascending",
        },
        binding_parameters={},
    )
    weighted = _selection("weighted_rank")
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id=project_id,
        nodes=(_source(), _scorer(), filter_node, weighted),
        edges=(
            *_scorer_edges(),
            *_selection_edges("filter"),
            *_selection_edges("select"),
        ),
        contract_lock=(),
        observation_selectors=_selectors(catalog),
        selection_objectives=_objectives(catalog),
    )

    with TestClient(create_application(frozen_catalog_override=catalog)) as client:
        committed = _commit_public_workflow(
            client,
            project_id,
            workflow,
        )

        def forbid_execution_lookup(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(
                "Run execution must use commit-time resolved plan facts"
            )

        for method_name in (
            "get_contract",
            "get_port_type",
            "require_contract",
            "require_port_type",
            "require_reference",
            "resolve_contract_closure",
        ):
            monkeypatch.setattr(
                FrozenCatalog,
                method_name,
                forbid_execution_lookup,
            )

        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "resolved-selection-plan",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert {
        result["selection_node_id"]
        for result in projection["selection_results"]
    } == {"filter", "select"}


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
        create_application(frozen_catalog_override=catalog)
    ) as client:
        committed = _commit_public_workflow(
            client,
            project_id,
            workflow,
        )

        projections = []
        for request_id in ("multi-objective-first", "multi-objective-replay"):
            started = client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_commit_id": committed[
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
            selected_output = next(
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
                    selected_output,
                )[0]
            )

    selected_ids = []
    for projection, selected_value in zip(
        projections,
        selected_values,
        strict=True,
    ):
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
            for item in selected_value["fields"]["items"]
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


def test_selection_conclusion_and_run_terminal_publish_as_one_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, project_id, workflow, roots = _selection_public_scope(
        tmp_path,
        monkeypatch,
        "atomic selection closure",
    )

    with TestClient(
        create_application(frozen_catalog_override=catalog)
    ) as client:
        committed = _commit_public_workflow(client, project_id, workflow)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "atomic-selection-closure",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )
        events = public_run_events(
            client.app.state.run_runtime,
            project_id,
            run_id,
        )

    transactions = [
        json.loads(path.read_text())
        for path in sorted(
            (roots["RUN"] / project_id / run_id / "ledger").glob("*.json")
        )
    ]
    closure = next(
        transaction
        for transaction in transactions
        if any(
            fact["fact_type"] == "run_terminal"
            for fact in transaction["facts"]
        )
    )

    assert projection["status"] == "succeeded"
    assert [
        fact["fact_type"] for fact in closure["facts"]
    ] == ["selection_terminal", "run_terminal"]
    assert closure["facts"][0]["payload"]["result"] == (
        projection["selection_results"][0]
    )
    assert closure["facts"][1]["payload"] == {"status": "succeeded"}
    assert [
        event["event"]["type"] for event in events[-2:]
    ] == ["selection_terminal", "run_terminal"]
    assert {
        fact["payload"]["node_id"]
        for transaction in transactions[:-1]
        for fact in transaction["facts"]
        if fact["fact_type"] == "node_disposition"
    } == {"canonical-source", "canonical-scores", "select"}


def test_selection_derivation_failure_closes_selection_and_run_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, project_id, workflow, roots = _selection_public_scope(
        tmp_path,
        monkeypatch,
        "failed selection closure",
    )

    def fail_selection_derivation(*_args: Any, **_kwargs: Any) -> None:
        raise SelectionError(
            "Selection Objective AKIAABCDEFGHIJKLMNOP cannot be derived"
        )

    monkeypatch.setattr(
        run_runtime,
        "selection_consumer_result",
        fail_selection_derivation,
    )

    with TestClient(
        create_application(frozen_catalog_override=catalog)
    ) as client:
        committed = _commit_public_workflow(client, project_id, workflow)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "failed-selection-closure",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )
        events = public_run_events(
            client.app.state.run_runtime,
            project_id,
            run_id,
        )

    closure = next(
        json.loads(path.read_text())
        for path in sorted(
            (roots["RUN"] / project_id / run_id / "ledger").glob("*.json")
        )
        if b'"fact_type":"run_terminal"' in path.read_bytes()
    )
    assert projection["status"] == "failed"
    assert projection["selection_results"] == []
    assert projection["selection_error"]["code"] == "selection_failed"
    assert projection["selection_error"]["details"] == {
        "reason": "Selection Objective AKIAABCDEFGHIJKLMNOP cannot be derived"
    }
    assert [fact["fact_type"] for fact in closure["facts"]] == [
        "selection_terminal",
        "run_terminal",
    ]
    assert [fact["payload"]["status"] for fact in closure["facts"]] == [
        "failed",
        "failed",
    ]
    assert [event["event"]["type"] for event in events[-2:]] == [
        "selection_terminal",
        "run_terminal",
    ]


def test_run_closure_failure_publishes_neither_selection_nor_run_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, project_id, workflow, roots = _selection_public_scope(
        tmp_path,
        monkeypatch,
        "unavailable selection closure",
    )

    with TestClient(
        create_application(
            frozen_catalog_override=catalog,
            ledger_transaction_store=_FailRunClosureStore(),
        )
    ) as client:
        committed = _commit_public_workflow(client, project_id, workflow)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "unavailable-selection-closure",
            },
        )

    assert started.status_code == 503
    assert started.json()["error"]["code"] == "evidence_unavailable"
    durable_facts = [
        fact
        for path in sorted(roots["RUN"].rglob("ledger/*.json"))
        for fact in json.loads(path.read_text())["facts"]
    ]
    assert {
        fact["payload"]["node_id"]
        for fact in durable_facts
        if fact["fact_type"] == "node_disposition"
    } == {"canonical-source", "canonical-scores", "select"}
    assert not any(
        fact["fact_type"] in {"selection_terminal", "run_terminal"}
        for fact in durable_facts
    )


def test_compiler_rejects_selection_objective_with_multiple_consumers(
) -> None:
    catalog = _catalog()
    weighted = replace(
        _selection("weighted_rank"),
        node_id="select-weighted",
    )
    pareto = replace(
        _selection("pareto"),
        node_id="select-pareto",
    )
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id="multiply-consumed-objectives",
        nodes=(_source(), _scorer(), weighted, pareto),
        edges=(
            *_scorer_edges(),
            *_selection_edges("select-weighted"),
            *_selection_edges("select-pareto"),
        ),
        contract_lock=(),
        selection_objectives=_objectives(catalog),
    )

    with pytest.raises(WorkflowCompileError) as raised:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert raised.value.code == "multiple_selection_objective_consumers"
    assert raised.value.field_path == ("selection_objectives", 0)
