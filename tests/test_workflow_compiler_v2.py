"""Public-seam tests for contract-locked v2 Workflow compilation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from core import (
    BehaviorReference,
    CatalogBuildError,
    CatalogContract,
    FrozenCatalog,
    OperationContext,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
    builtin_frozen_catalog,
)
from core.workflow_v2 import (
    CompiledWorkflow,
    ContractLockEntry,
    WorkflowCompileError,
    WorkflowDocument,
    WorkflowDocumentError,
    compile_workflow,
    parse_workflow_document,
    relock_workflow,
    validate_workflow_parameter_values,
)
from core.port_types import (
    InactiveContractGenerationError,
    UnknownContractError,
)
from core.server import create_app
from protein_workbench_public import validate_error, validate_response


def _catalog_contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict,
) -> CatalogContract:
    return CatalogContract(
        contract_kind=contract_kind,
        contract_id=contract_id,
        contract_version="2.1.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
            "contract_version": "2.1.0",
            **descriptor,
        },
    )


def _workflow_catalog(
    *,
    source_available: bool = True,
    include_unreachable: bool = False,
    source_algorithm: str = "source",
    sink_port_type_id: str = "text",
    sink_port_type_version: str = "2.1.0",
    source_output_multiplicity: str = "one",
    sink_input_multiplicity: str = "one",
    factory_calls: list[str] | None = None,
    source_node_parameter_overrides: dict | None = None,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    text = builtin.require_port_type("text", "2.1.0")
    sink_port_type = builtin.require_port_type(
        sink_port_type_id,
        sink_port_type_version,
    )
    source_method = _catalog_contract(
        "method",
        "synthetic.source.method",
        {"algorithm_identity": {"name": source_algorithm}},
    )
    sink_method = _catalog_contract(
        "method",
        "synthetic.sink.method",
        {"algorithm_identity": {"name": "sink"}},
    )
    metric = _catalog_contract(
        "metric",
        "synthetic.identity",
        {
            "value_shape": "scalar",
            "unit": "dimensionless",
            "canonical_range": {"minimum": 0, "maximum": 1},
            "validation_contract": {"finite": True},
            "observation_context_schema": {"kind": "intrinsic"},
        },
    )
    utility = _catalog_contract(
        "utility_transform",
        "synthetic.identity",
        {
            "compatible_input_contract": {
                "metric": metric.reference(),
                "method": source_method.reference(),
            },
            "output_contract": {"minimum": 0, "maximum": 1},
        },
    )
    parameter_overrides = {
        name: {
            "parameter_scope": "scientific",
            "scientific_meaning": f"Synthetic scientific parameter {name}",
            **declaration,
        }
        for name, declaration in (
            source_node_parameter_overrides or {}
        ).items()
    }
    source_node = _catalog_contract(
        "node_type",
        "synthetic.source",
        {
            "inputs": [],
            "outputs": [
                {
                    "name": "text",
                    "port_type": text.reference(),
                    "required": True,
                    "multiplicity": source_output_multiplicity,
                    "scientific_meaning": (
                        "Synthetic textual scientific value emitted by the "
                        "source"
                    ),
                }
            ],
            "node_parameters": {
                "uppercase": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": (
                        "Whether the scientific text transform uses uppercase"
                    ),
                    "value_contract": {"type": "boolean"},
                    "required": True,
                    "utility_transform": utility.reference(),
                },
                "label": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": (
                        "Stable scientific label attached to source output"
                    ),
                    "value_contract": {"type": "string"},
                    "default": "default-label",
                },
                **parameter_overrides,
            },
        },
    )
    sink_node = _catalog_contract(
        "node_type",
        "synthetic.sink",
        {
            "inputs": [
                {
                    "name": "text",
                    "port_type": sink_port_type.reference(),
                    "required": True,
                    "multiplicity": sink_input_multiplicity,
                    "scientific_meaning": (
                        "Synthetic textual scientific value consumed by the "
                        "sink"
                    ),
                }
            ],
            "outputs": [
                {
                    "name": "text",
                    "port_type": sink_port_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": (
                        "Synthetic textual scientific value emitted by the "
                        "sink"
                    ),
                }
            ],
            "node_parameters": {},
        },
    )
    source_binding = _catalog_contract(
        "binding",
        "synthetic.source.direct",
        {
            "node_type": source_node.reference(),
            "method": source_method.reference(),
            "binding_parameters": {
                "batch_size": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": (
                        "Synthetic batch cardinality used by this Binding"
                    ),
                    "value_contract": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "required": True,
                }
            },
            "produced_observations": [
                {
                    "output_port": "text",
                    "metric": metric.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "output",
                    "subject_port": "text",
                    "guaranteed_multiplicity": source_output_multiplicity,
                }
            ],
        },
    )
    sink_binding = _catalog_contract(
        "binding",
        "synthetic.sink.direct",
        {
            "node_type": sink_node.reference(),
            "method": sink_method.reference(),
            "binding_parameters": {},
            "produced_observations": [],
        },
    )
    contracts = [
        source_method,
        sink_method,
        metric,
        utility,
        source_node,
        sink_node,
        source_binding,
        sink_binding,
    ]
    if include_unreachable:
        contracts.append(
            _catalog_contract(
                "method",
                "synthetic.unreachable.method",
                {"algorithm_identity": {"name": "unreachable"}},
            )
        )

    calls = factory_calls if factory_calls is not None else []

    def _factory(_context: OperationContext) -> object:
        calls.append("factory")
        raise AssertionError("Workflow compilation constructed an implementation")

    factories = {
        ("synthetic.source.direct", "2.1.0"): ScientificOperationFactory(
            behavior=BehaviorReference(
                "synthetic.source/factory",
                "2.1.0",
                {},
            ),
            build=_factory,
        ),
        ("synthetic.sink.direct", "2.1.0"): ScientificOperationFactory(
            behavior=BehaviorReference(
                "synthetic.sink/factory",
                "2.1.0",
                {},
            ),
            build=_factory,
        ),
    }
    readiness_declarations = {
        (binding_id, "2.1.0"): ReadinessDeclaration(
            behavior=BehaviorReference(
                f"{binding_id}/readiness",
                "2.1.0",
                {},
            ),
            prerequisites={},
            check=lambda _input: ReadinessResult(True),
        )
        for binding_id in (
            "synthetic.source.direct",
            "synthetic.sink.direct",
        )
    }
    observed_at = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)
    availability = (
        {
            "binding": source_binding.reference(),
            "observed_at": "2026-07-29T04:00:00Z",
            "available": source_available,
            **(
                {}
                if source_available
                else {
                    "reason": {
                        "code": "missing_runtime",
                        "message": "Synthetic runtime is not installed",
                        "retryable": False,
                    }
                }
            ),
        },
        {
            "binding": sink_binding.reference(),
            "observed_at": "2026-07-29T04:00:00Z",
            "available": True,
        },
    )
    return FrozenCatalog(
        builtin.port_types,
        contracts=tuple(contracts),
        availability=availability,
        availability_observed_at=observed_at,
        factories=factories,
        readiness_declarations=readiness_declarations,
    )


def _unlocked_workflow() -> WorkflowDocument:
    return parse_workflow_document(
        {
            "schema_version": "2.1.0",
            "workflow_id": "workflow-1",
            "nodes": [
                {
                    "node_id": "source",
                    "node_type_id": "synthetic.source",
                    "node_type_version": "2.1.0",
                    "binding_id": "synthetic.source.direct",
                    "binding_version": "2.1.0",
                    "node_parameters": {"uppercase": True},
                    "binding_parameters": {"batch_size": 2},
                },
                {
                    "node_id": "sink",
                    "node_type_id": "synthetic.sink",
                    "node_type_version": "2.1.0",
                    "binding_id": "synthetic.sink.direct",
                    "binding_version": "2.1.0",
                    "node_parameters": {},
                    "binding_parameters": {},
                },
            ],
            "edges": [
                {
                    "source_node_id": "source",
                    "source_port": "text",
                    "target_node_id": "sink",
                    "target_port": "text",
                }
            ],
            "contract_lock": [],
        }
    )


@pytest.mark.parametrize(
    ("contract_kind", "contract_id"),
    [
        ("node_type", "synthetic.source"),
        ("port_type", "text"),
    ],
)
def test_catalog_resolution_distinguishes_inactive_generation_from_unknown(
    contract_kind: str,
    contract_id: str,
) -> None:
    catalog = _workflow_catalog()

    with pytest.raises(InactiveContractGenerationError) as inactive:
        catalog.require_contract(
            contract_kind,
            contract_id,
            "2.0.0",
        )
    with pytest.raises(UnknownContractError) as unknown:
        catalog.require_contract(
            contract_kind,
            "synthetic.missing",
            "2.0.0",
        )

    assert catalog.get_contract(contract_kind, contract_id, "2.0.0") is None
    assert inactive.value.requested_version == "2.0.0"
    assert inactive.value.active_version == "2.1.0"
    assert unknown.value.contract_id == "synthetic.missing"


@pytest.mark.parametrize(
    "version_field",
    ["node_type_version", "binding_version"],
)
@pytest.mark.parametrize("seam", ["save", "relock", "compile"])
def test_workflow_exact_resolution_reports_inactive_generation_at_version(
    version_field: str,
    seam: str,
) -> None:
    catalog = _workflow_catalog()
    workflow = _unlocked_workflow()
    stale_node = replace(
        workflow.nodes[0],
        **{version_field: "2.0.0"},
    )
    stale = replace(
        workflow,
        nodes=(stale_node, workflow.nodes[1]),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        if seam == "save":
            validate_workflow_parameter_values(stale, catalog)
        elif seam == "relock":
            relock_workflow(stale, catalog)
        else:
            compile_workflow(
                stale,
                workflow_commit_revision=1,
                catalog=catalog,
            )

    assert captured.value.code == "inactive_generation"
    assert captured.value.field_path == ("nodes", 0, version_field)


def _workflow_with_reference_generation(
    catalog: FrozenCatalog,
    *,
    collection: str,
    reference_field: str,
    contract_version: str,
) -> WorkflowDocument:
    metric = catalog.require_contract(
        "metric",
        "synthetic.identity",
        "2.1.0",
    ).reference()
    method = catalog.require_contract(
        "method",
        "synthetic.source.method",
        "2.1.0",
    ).reference()
    utility = catalog.require_contract(
        "utility_transform",
        "synthetic.identity",
        "2.1.0",
    ).reference()
    selected_reference = {
        "metric": metric,
        "method": method,
        "utility_transform": utility,
    }[reference_field]
    selected_reference["contract_version"] = contract_version
    common = {
        "candidate_input": {
            "node_id": "source",
            "output_port": "text",
        },
        "score_collection_input": {
            "node_id": "source",
            "output_port": "text",
        },
        "source_partition": "default",
        "metric": metric,
        "method": method,
        "context_selector": {"kind": "intrinsic"},
        "match_cardinality": "exactly_one",
        "missing_policy": "error",
    }
    payload = _unlocked_workflow().to_public()
    if collection == "observation_selectors":
        payload[collection] = [
            {
                "selector_id": "selector-1",
                **common,
            }
        ]
    else:
        payload[collection] = [
            {
                "objective_id": "objective-1",
                **common,
                "utility_transform": utility,
                "utility_parameters": {},
                "weight": 1,
            }
        ]
    return parse_workflow_document(payload)


@pytest.mark.parametrize(
    ("collection", "reference_field"),
    [
        ("observation_selectors", "metric"),
        ("observation_selectors", "method"),
        ("selection_objectives", "metric"),
        ("selection_objectives", "method"),
        ("selection_objectives", "utility_transform"),
    ],
)
@pytest.mark.parametrize("seam", ["save", "relock", "compile"])
def test_workflow_reference_reports_inactive_generation_at_version(
    collection: str,
    reference_field: str,
    seam: str,
) -> None:
    catalog = _workflow_catalog()
    stale = _workflow_with_reference_generation(
        catalog,
        collection=collection,
        reference_field=reference_field,
        contract_version="2.0.0",
    )

    with pytest.raises(WorkflowCompileError) as captured:
        if seam == "save":
            validate_workflow_parameter_values(stale, catalog)
        elif seam == "relock":
            relock_workflow(stale, catalog)
        else:
            compile_workflow(
                stale,
                workflow_commit_revision=1,
                catalog=catalog,
            )

    assert captured.value.code == "inactive_generation"
    assert captured.value.field_path == (
        collection,
        0,
        reference_field,
        "contract_version",
    )


@pytest.mark.parametrize(
    ("collection", "reference_field"),
    [
        ("observation_selectors", "metric"),
        ("observation_selectors", "method"),
        ("selection_objectives", "metric"),
        ("selection_objectives", "method"),
        ("selection_objectives", "utility_transform"),
    ],
)
@pytest.mark.parametrize("seam", ["save", "relock", "compile"])
def test_unknown_workflow_reference_reports_the_contract_id_field(
    collection: str,
    reference_field: str,
    seam: str,
) -> None:
    catalog = _workflow_catalog()
    payload = _workflow_with_reference_generation(
        catalog,
        collection=collection,
        reference_field=reference_field,
        contract_version="2.1.0",
    ).to_public()
    payload[collection][0][reference_field]["contract_id"] = (
        "synthetic.missing"
    )
    unknown = parse_workflow_document(payload)

    with pytest.raises(WorkflowCompileError) as captured:
        if seam == "save":
            validate_workflow_parameter_values(unknown, catalog)
        elif seam == "relock":
            relock_workflow(unknown, catalog)
        else:
            compile_workflow(
                unknown,
                workflow_commit_revision=1,
                catalog=catalog,
            )

    assert captured.value.code == "unknown_contract"
    assert captured.value.field_path == (
        collection,
        0,
        reference_field,
        "contract_id",
    )


@pytest.mark.parametrize(
    ("collection", "reference_field"),
    [
        ("observation_selectors", "metric"),
        ("observation_selectors", "method"),
        ("selection_objectives", "metric"),
        ("selection_objectives", "method"),
        ("selection_objectives", "utility_transform"),
    ],
)
@pytest.mark.parametrize("seam", ["save", "relock", "compile"])
def test_workflow_reference_rejects_a_mismatched_contract_kind_at_kind_field(
    collection: str,
    reference_field: str,
    seam: str,
) -> None:
    catalog = _workflow_catalog()
    payload = _workflow_with_reference_generation(
        catalog,
        collection=collection,
        reference_field=reference_field,
        contract_version="2.1.0",
    ).to_public()
    payload[collection][0][reference_field]["contract_kind"] = {
        "metric": "method",
        "method": "metric",
        "utility_transform": "method",
    }[reference_field]
    mismatched = parse_workflow_document(payload)

    with pytest.raises(WorkflowCompileError) as captured:
        if seam == "save":
            validate_workflow_parameter_values(mismatched, catalog)
        elif seam == "relock":
            relock_workflow(mismatched, catalog)
        else:
            compile_workflow(
                mismatched,
                workflow_commit_revision=1,
                catalog=catalog,
            )

    assert captured.value.code == "contract_kind_mismatch"
    assert captured.value.field_path == (
        collection,
        0,
        reference_field,
        "contract_kind",
    )


@pytest.mark.parametrize(
    ("collection", "reference_field"),
    [
        ("observation_selectors", "metric"),
        ("observation_selectors", "method"),
        ("selection_objectives", "metric"),
        ("selection_objectives", "method"),
        ("selection_objectives", "utility_transform"),
    ],
)
def test_compile_reports_workflow_reference_digest_drift_at_digest(
    collection: str,
    reference_field: str,
) -> None:
    catalog = _workflow_catalog()
    locked = relock_workflow(
        _workflow_with_reference_generation(
            catalog,
            collection=collection,
            reference_field=reference_field,
            contract_version="2.1.0",
        ),
        catalog,
    ).to_public()
    locked[collection][0][reference_field]["contract_digest"] = (
        "sha256:" + ("f" * 64)
    )
    drifted = parse_workflow_document(locked)

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            drifted,
            workflow_commit_revision=1,
            catalog=catalog,
        )

    assert captured.value.code == "contract_digest_mismatch"
    assert captured.value.field_path == (
        collection,
        0,
        reference_field,
        "contract_digest",
    )


def test_compile_returns_only_an_immutable_private_plan() -> None:
    catalog = _workflow_catalog()
    workflow = relock_workflow(_unlocked_workflow(), catalog)

    compiled = compile_workflow(
        workflow,
        workflow_commit_revision=2,
        catalog=catalog,
    )

    assert isinstance(compiled, CompiledWorkflow)
    assert compiled.execution_plan.node_order == ("source", "sink")
    assert compiled.execution_plan.workflow_commit_revision == 2
    assert compiled.execution_plan.resolved_contracts == workflow.contract_lock
    assert compiled.execution_plan.nodes[0].node_parameters == {
        "uppercase": True,
        "label": "default-label",
    }
    assert not hasattr(compiled, "receipt")
    assert not hasattr(compiled, "public_receipt")
    with pytest.raises(FrozenInstanceError):
        compiled.execution_plan.workflow_commit_revision = 3  # type: ignore[misc]
    with pytest.raises(TypeError):
        compiled.execution_plan.nodes[0].node_parameters["uppercase"] = False


def test_execution_plan_identity_excludes_runtime_handles() -> None:
    first_catalog = _workflow_catalog(factory_calls=[])
    second_catalog = _workflow_catalog(factory_calls=[])
    first_workflow = relock_workflow(
        _unlocked_workflow(),
        first_catalog,
    )
    second_workflow = relock_workflow(
        _unlocked_workflow(),
        second_catalog,
    )

    first = compile_workflow(
        first_workflow,
        workflow_commit_revision=2,
        catalog=first_catalog,
    )
    second = compile_workflow(
        second_workflow,
        workflow_commit_revision=2,
        catalog=second_catalog,
    )

    assert first_catalog.factories[
        ("synthetic.source.direct", "2.1.0")
    ] is not second_catalog.factories[
        ("synthetic.source.direct", "2.1.0")
    ]
    assert first_catalog.readiness_declarations[
        ("synthetic.source.direct", "2.1.0")
    ] is not second_catalog.readiness_declarations[
        ("synthetic.source.direct", "2.1.0")
    ]
    assert first.execution_plan == second.execution_plan
    assert (
        first.execution_plan.execution_plan_digest
        == second.execution_plan.execution_plan_digest
    )


def test_execution_plan_copies_all_public_sequences_at_its_boundary() -> None:
    catalog = _workflow_catalog()
    compiled = compile_workflow(
        relock_workflow(_unlocked_workflow(), catalog),
        workflow_commit_revision=2,
        catalog=catalog,
    )
    plan = compiled.execution_plan

    copied = replace(
        plan,
        nodes=list(plan.nodes),  # type: ignore[arg-type]
        edges=list(plan.edges),  # type: ignore[arg-type]
        node_order=list(plan.node_order),  # type: ignore[arg-type]
        resolved_contracts=list(  # type: ignore[arg-type]
            plan.resolved_contracts
        ),
        observation_selectors=list(  # type: ignore[arg-type]
            plan.observation_selectors
        ),
        selection_objectives=list(  # type: ignore[arg-type]
            plan.selection_objectives
        ),
    )

    assert type(copied.nodes) is tuple
    assert type(copied.edges) is tuple
    assert type(copied.node_order) is tuple
    assert type(copied.resolved_contracts) is tuple
    assert type(copied.observation_selectors) is tuple
    assert type(copied.selection_objectives) is tuple


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "stale_extra", "digest_mismatch"],
)
def test_contract_lock_mismatch_fails_before_runtime_activity(
    mutation: str,
) -> None:
    factory_calls: list[str] = []
    catalog = _workflow_catalog(
        source_available=False,
        include_unreachable=True,
        factory_calls=factory_calls,
    )
    locked = relock_workflow(_unlocked_workflow(), catalog)
    entries = list(locked.contract_lock)
    if mutation == "missing":
        entries.pop()
    elif mutation == "duplicate":
        entries.append(entries[0])
    elif mutation == "stale_extra":
        unreachable = catalog.require_contract(
            "method",
            "synthetic.unreachable.method",
            "2.1.0",
        )
        entries.append(
            ContractLockEntry.from_public(unreachable.reference())
        )
        entries.sort()
    else:
        entries[0] = replace(
            entries[0],
            contract_digest="sha256:" + ("f" * 64),
        )
    mismatched = replace(locked, contract_lock=tuple(entries))

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            mismatched,
            workflow_commit_revision=2,
            catalog=catalog,
        )

    assert captured.value.code == "contract_digest_mismatch"
    assert captured.value.field_path == ("contract_lock",)
    assert factory_calls == []


def test_unreachable_catalog_change_does_not_invalidate_the_lock() -> None:
    catalog_a = _workflow_catalog()
    catalog_b = _workflow_catalog(include_unreachable=True)
    workflow = relock_workflow(_unlocked_workflow(), catalog_a)

    compiled = compile_workflow(
        workflow,
        workflow_commit_revision=2,
        catalog=catalog_b,
    )

    assert compiled.execution_plan.resolved_contracts == workflow.contract_lock
    assert catalog_a.contract_digest != catalog_b.contract_digest
    assert (
        compiled.execution_plan.catalog_contract_digest
        == catalog_b.contract_digest
    )


def test_reachable_contract_change_with_the_same_id_and_version_is_rejected() -> None:
    catalog_a = _workflow_catalog(source_algorithm="source-a")
    catalog_b = _workflow_catalog(source_algorithm="source-b")
    workflow = relock_workflow(_unlocked_workflow(), catalog_a)

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            workflow,
            workflow_commit_revision=2,
            catalog=catalog_b,
        )

    assert captured.value.code == "contract_digest_mismatch"


@pytest.mark.parametrize(
    ("field_name", "missing_id"),
    [
        ("node_type_id", "synthetic.missing"),
        ("binding_id", "synthetic.missing.direct"),
    ],
)
@pytest.mark.parametrize("seam", ["save", "relock", "compile"])
def test_unknown_selected_catalog_contract_reports_the_identity_field(
    field_name: str,
    missing_id: str,
    seam: str,
) -> None:
    catalog = _workflow_catalog()
    workflow = _unlocked_workflow()
    missing = replace(
        workflow.nodes[0],
        **{field_name: missing_id},
    )
    unresolved = replace(
        workflow,
        nodes=(missing, workflow.nodes[1]),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        if seam == "save":
            validate_workflow_parameter_values(unresolved, catalog)
        elif seam == "relock":
            relock_workflow(unresolved, catalog)
        else:
            compile_workflow(
                unresolved,
                workflow_commit_revision=1,
                catalog=catalog,
            )

    assert captured.value.code == "unknown_contract"
    assert captured.value.field_path == ("nodes", 0, field_name)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"schema_version": "2.0.0"}, "unsupported_schema_version"),
        (
            {
                "nodes": [
                    {
                        "node_id": "source",
                        "node_type_id": "synthetic.source",
                        "node_type_version": "latest",
                        "binding_id": "synthetic.source.direct",
                        "binding_version": "2.1.0",
                        "node_parameters": {"uppercase": True},
                        "binding_parameters": {"batch_size": 2},
                    }
                ]
            },
            "malformed_request",
        ),
        (
            {
                "nodes": [
                    {
                        "node_id": "source",
                        "node_type_id": "synthetic.source",
                        "node_type_version": ">=2.1.0",
                        "binding_id": "synthetic.source.direct",
                        "binding_version": "2.1.0",
                        "node_parameters": {"uppercase": True},
                        "binding_parameters": {"batch_size": 2},
                    }
                ]
            },
            "malformed_request",
        ),
        (
            {
                "nodes": [
                    {
                        "node_id": "source",
                        "node_type_id": "synthetic.source",
                        "node_type_version": "2.1.0",
                        "binding_version": "2.1.0",
                        "node_parameters": {"uppercase": True},
                        "binding_parameters": {"batch_size": 2},
                    }
                ]
            },
            "malformed_request",
        ),
        (
            {
                "nodes": [
                    {
                        "node_id": "source",
                        "node_type_id": "synthetic.source",
                        "node_type_version": "2.1.0",
                        "binding_id": "synthetic.source.direct",
                        "binding_version": "2.1.0",
                        "method_id": "synthetic.source.method",
                        "node_parameters": {"uppercase": True},
                        "binding_parameters": {"batch_size": 2},
                    }
                ]
            },
            "malformed_request",
        ),
        ({"fallback_binding_id": "synthetic.sink.direct"}, "malformed_request"),
    ],
)
def test_v1_ranges_latest_auto_binding_method_and_fallback_fail_closed(
    mutation: dict,
    expected_code: str,
) -> None:
    payload = _unlocked_workflow().to_public()
    payload.update(mutation)

    with pytest.raises(WorkflowDocumentError) as captured:
        parse_workflow_document(payload)

    assert captured.value.code == expected_code


@pytest.mark.parametrize(
    "environment_parameter",
    ["api_key", "credential", "device", "endpoint", "model_name", "runtime_path"],
)
def test_environment_and_model_identity_cannot_enter_workflow_parameters(
    environment_parameter: str,
) -> None:
    catalog = _workflow_catalog()
    workflow = _unlocked_workflow()
    source = replace(
        workflow.nodes[0],
        binding_parameters={
            **workflow.nodes[0].binding_parameters,
            environment_parameter: "forbidden",
        },
    )
    locked = relock_workflow(
        replace(workflow, nodes=(source, workflow.nodes[1])),
        catalog,
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            locked,
            workflow_commit_revision=2,
            catalog=catalog,
        )

    assert captured.value.code == "environment_parameter_forbidden"


def test_compile_validates_dag_binding_ownership_parameters_ports_and_availability() -> None:
    base = _unlocked_workflow()
    source, sink = base.nodes

    cases = [
        (
            "workflow_cycle",
            _workflow_catalog(),
            replace(
                base,
                nodes=(sink,),
                edges=(
                    replace(
                        base.edges[0],
                        source_node_id="sink",
                        target_node_id="sink",
                    ),
                ),
            ),
        ),
        (
            "binding_ownership_mismatch",
            _workflow_catalog(),
            replace(
                base,
                nodes=(
                    replace(
                        source,
                        binding_id="synthetic.sink.direct",
                        binding_parameters={},
                    ),
                    sink,
                ),
            ),
        ),
        (
            "invalid_parameter",
            _workflow_catalog(),
            replace(
                base,
                nodes=(
                    replace(source, binding_parameters={"batch_size": 0}),
                    sink,
                ),
            ),
        ),
        (
            "required_parameter_missing",
            _workflow_catalog(),
            replace(
                base,
                nodes=(replace(source, node_parameters={}), sink),
            ),
        ),
        (
            "port_type_mismatch",
            _workflow_catalog(
                sink_port_type_id="protein.sequence",
                sink_port_type_version="3.0.0",
            ),
            base,
        ),
        (
            "required_input_missing",
            _workflow_catalog(),
            replace(base, edges=()),
        ),
        (
            "source_port_not_found",
            _workflow_catalog(),
            replace(
                base,
                edges=(replace(base.edges[0], source_port="missing"),),
            ),
        ),
    ]

    for expected_code, catalog, workflow in cases:
        locked = relock_workflow(workflow, catalog)
        with pytest.raises(WorkflowCompileError) as captured:
            compile_workflow(
                locked,
                workflow_commit_revision=2,
                catalog=catalog,
            )
        assert captured.value.code == expected_code


def test_compile_keeps_an_unavailable_binding_for_cache_first_execution() -> None:
    catalog = _workflow_catalog(source_available=False)
    workflow = relock_workflow(_unlocked_workflow(), catalog)

    plan = compile_workflow(
        workflow,
        workflow_commit_revision=2,
        catalog=catalog,
    )

    assert plan.execution_plan.nodes[0].binding.contract_id == (
        "synthetic.source.direct"
    )


def test_compile_rejects_many_output_connected_to_one_input() -> None:
    catalog = _workflow_catalog(source_output_multiplicity="many")
    workflow = relock_workflow(_unlocked_workflow(), catalog)

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            workflow,
            workflow_commit_revision=2,
            catalog=catalog,
        )

    assert captured.value.code == "port_multiplicity_mismatch"
    assert captured.value.field_path == ("edges", 0)


@pytest.mark.parametrize(
    ("source_multiplicity", "target_multiplicity"),
    [("one", "many"), ("many", "many")],
)
def test_compile_accepts_connections_that_preserve_all_output_values(
    source_multiplicity: str,
    target_multiplicity: str,
) -> None:
    catalog = _workflow_catalog(
        source_output_multiplicity=source_multiplicity,
        sink_input_multiplicity=target_multiplicity,
    )
    workflow = relock_workflow(_unlocked_workflow(), catalog)

    compiled = compile_workflow(
        workflow,
        workflow_commit_revision=2,
        catalog=catalog,
    )

    assert compiled.execution_plan.edges == workflow.edges


def test_compile_rejects_multiple_scalar_edges_to_one_input() -> None:
    catalog = _workflow_catalog()
    workflow = _unlocked_workflow()
    source, sink = workflow.nodes
    second_source = replace(source, node_id="source-2")
    second_edge = replace(
        workflow.edges[0],
        source_node_id=second_source.node_id,
    )
    workflow = replace(
        workflow,
        nodes=(source, second_source, sink),
        edges=(*workflow.edges, second_edge),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            relock_workflow(workflow, catalog),
            workflow_commit_revision=2,
            catalog=catalog,
        )

    assert captured.value.code == "duplicate_input_connection"
    assert captured.value.field_path == ("edges", 1, "target_port")


@pytest.mark.parametrize(
    ("declaration", "value"),
    [
        ({"type": "string", "enum": ["safe"]}, "unsafe"),
        ({"type": "number", "maximum": 1}, 1.5),
        (
            {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string", "minLength": 2},
            },
            ["x"],
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["count"],
                "properties": {
                    "count": {
                        "field_scope": "scientific",
                        "scientific_meaning": (
                            "Synthetic scientific observation count"
                        ),
                        "type": "integer",
                        "minimum": 1,
                    },
                },
            },
            {"count": 0, "extra": True},
        ),
    ],
)
def test_compile_enforces_complete_nested_parameter_value_contract(
    declaration: dict,
    value: object,
) -> None:
    catalog = _workflow_catalog(
        source_node_parameter_overrides={
            "options": {"value_contract": declaration}
        }
    )
    workflow = _unlocked_workflow()
    source, sink = workflow.nodes
    workflow = replace(
        workflow,
        nodes=(
            replace(
                source,
                node_parameters={
                    **source.node_parameters,
                    "options": value,
                },
            ),
            sink,
        ),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            relock_workflow(workflow, catalog),
            workflow_commit_revision=2,
            catalog=catalog,
        )

    assert captured.value.code == "invalid_parameter"


@pytest.mark.parametrize(
    "forbidden_name",
    [
        "apiToken",
        "accessKey",
        "awsAccessKeyId",
        "baseURL",
        "credentialHandle",
        "gpuDevice",
        "modelPath",
        "password",
        "runtime.path",
        "serviceURI",
        "sshKey",
        "auth_header",
    ],
)
def test_compile_rejects_nested_environment_configuration_fields(
    forbidden_name: str,
) -> None:
    catalog = _workflow_catalog(
        source_node_parameter_overrides={
            "scientific_options": {
                "value_contract": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "sampling": {
                            "field_scope": "scientific",
                            "scientific_meaning": (
                                "Scientific sampling configuration"
                            ),
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "temperature": {
                                    "field_scope": "scientific",
                                    "scientific_meaning": (
                                        "Scientific sampling temperature"
                                    ),
                                    "type": "number",
                                },
                            },
                        }
                    },
                },
            }
        }
    )
    workflow = _unlocked_workflow()
    source, sink = workflow.nodes
    workflow = replace(
        workflow,
        nodes=(
            replace(
                source,
                node_parameters={
                    **source.node_parameters,
                    "scientific_options": {
                        "sampling": {
                            forbidden_name: "must-not-persist",
                        },
                    },
                },
            ),
            sink,
        ),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(
            relock_workflow(workflow, catalog),
            workflow_commit_revision=2,
            catalog=catalog,
        )

    assert captured.value.code == "environment_parameter_forbidden"


@pytest.mark.parametrize(
    "unsupported_contract",
    [
        {"type": "integer", "multipleOf": 2},
        {"not": {"const": "x"}},
        {"type": "array", "contains": {"const": "x"}},
        {"if": {"const": "x"}, "then": {"const": "y"}},
        {"type": "object", "patternProperties": {"^x": {"type": "string"}}},
        {"type": "object", "dependentRequired": {"x": ["y"]}},
    ],
)
def test_catalog_rejects_unsupported_parameter_contract_keywords(
    unsupported_contract: dict,
) -> None:
    with pytest.raises(CatalogBuildError, match="unsupported"):
        _workflow_catalog(
            source_node_parameter_overrides={
                "closed_contract": {
                    "value_contract": unsupported_contract
                },
            }
        )


@pytest.mark.parametrize(
    "environment_name",
    [
        "apiToken",
        "accessKey",
        "awsAccessKeyId",
        "baseURL",
        "credentialHandle",
        "gpuDevice",
        "modelPath",
        "password",
        "runtime.path",
        "serviceURI",
        "sshKey",
        "auth_header",
    ],
)
def test_catalog_rejects_environment_parameter_declarations(
    environment_name: str,
) -> None:
    with pytest.raises(CatalogBuildError, match="Environment Configuration"):
        _workflow_catalog(
            source_node_parameter_overrides={
                environment_name: {"type": "string"},
            }
        )


@pytest.mark.parametrize(
    "malformed_contract",
    [
        {"type": "integer", "minimum": "bad"},
        {"type": "string", "pattern": 7},
        {"type": "string", "enum": 3},
        {
            "value_contract": {
                "type": "object",
                "additionalProperties": False,
                "required": True,
            },
        },
        {"type": "array", "uniqueItems": "yes"},
        {"type": "bogus"},
        {"type": "integer", "minimum": 1, "default": 0},
        {"type": "string", "enum": None},
        {"type": None},
        {"type": "number", "maximum": None},
        {"type": "string", "pattern": None},
        {"type": "array", "uniqueItems": None},
        {"value_contract": {"type": "object", "required": None}},
        {"type": "array", "items": None},
        {"type": "object", "properties": None},
        {"type": "object", "additionalProperties": None},
    ],
)
def test_catalog_rejects_malformed_supported_parameter_contracts(
    malformed_contract: dict,
) -> None:
    with pytest.raises(CatalogBuildError):
        _workflow_catalog(
            source_node_parameter_overrides={
                "malformed_contract": (
                    malformed_contract
                    if "value_contract" in malformed_contract
                    else {"value_contract": malformed_contract}
                ),
            }
        )


@pytest.mark.parametrize(
    "incomplete_contract",
    [
        {"value_contract": {}},
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "measurement": {
                    "field_scope": "scientific",
                    "scientific_meaning": "Incomplete scientific field",
                }
            },
        },
    ],
)
def test_catalog_rejects_parameter_contracts_without_a_discriminator(
    incomplete_contract: dict,
) -> None:
    with pytest.raises(CatalogBuildError, match="must declare"):
        _workflow_catalog(
            source_node_parameter_overrides={
                "incomplete_contract": (
                    incomplete_contract
                    if "value_contract" in incomplete_contract
                    else {"value_contract": incomplete_contract}
                ),
            }
        )


def test_catalog_rejects_flat_v20_parameter_value_schema() -> None:
    with pytest.raises(CatalogBuildError, match="value_contract"):
        _workflow_catalog(
            source_node_parameter_overrides={
                "legacy_flat": {"type": "string"},
            }
        )


@pytest.mark.parametrize(
    "classification",
    [
        {"parameter_scope": "environment"},
        {"scientific_meaning": ""},
    ],
)
def test_catalog_requires_explicit_scientific_parameter_classification(
    classification: dict,
) -> None:
    with pytest.raises(CatalogBuildError):
        _workflow_catalog(
            source_node_parameter_overrides={
                "temperature": {
                    "value_contract": {"type": "number"},
                    **classification,
                },
            }
        )


@pytest.mark.parametrize(
    "property_declaration",
    [
        {"measurement": {"type": "string"}},
        {
            "connectionString": {
                "field_scope": "scientific",
                "scientific_meaning": "Invalid database endpoint disguise",
                "type": "string",
            }
        },
        {
            "tlsCertificate": {
                "field_scope": "scientific",
                "scientific_meaning": "Invalid runtime certificate disguise",
                "type": "string",
            }
        },
    ],
)
def test_catalog_classifies_nested_scientific_fields_explicitly(
    property_declaration: dict,
) -> None:
    with pytest.raises(CatalogBuildError):
        _workflow_catalog(
            source_node_parameter_overrides={
                "scientific_options": {
                    "value_contract": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": property_declaration,
                    },
                },
            }
        )


@pytest.mark.parametrize(
    ("value_contract", "value"),
    [
        (
            {
                "anyOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["x"],
                        "properties": {
                            "x": {
                                "field_scope": "scientific",
                                "scientific_meaning": (
                                    "Synthetic scientific coordinate"
                                ),
                                "type": "integer",
                            }
                        },
                    },
                    {"type": "string"},
                ]
            },
            {"x": 1},
        ),
        ({"const": {"x": 1}}, {"x": 1}),
    ],
)
def test_compile_accepts_object_values_delegated_by_value_contract(
    value_contract: dict,
    value: object,
) -> None:
    catalog = _workflow_catalog(
        source_node_parameter_overrides={
            "choice": {"value_contract": value_contract},
        }
    )
    workflow = _unlocked_workflow()
    source, sink = workflow.nodes
    workflow = replace(
        workflow,
        nodes=(
            replace(
                source,
                node_parameters={
                    **source.node_parameters,
                    "choice": value,
                },
            ),
            sink,
        ),
    )

    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_commit_revision=2,
        catalog=catalog,
    )

    assert compiled.execution_plan.nodes[0].node_parameters["choice"] == value


@pytest.mark.parametrize(
    "inline_contract",
    [
        {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["x"],
                    "properties": {
                        "x": {
                            "field_scope": "scientific",
                            "scientific_meaning": (
                                "Synthetic required scientific coordinate"
                            ),
                            "type": "integer",
                        }
                    },
                },
                {"type": "string"},
            ]
        },
        {"const": {"x": 1}},
    ],
)
def test_required_parameter_metadata_is_not_object_schema(
    inline_contract: dict,
) -> None:
    catalog = _workflow_catalog(
        source_node_parameter_overrides={
            "choice": {
                "required": True,
                "value_contract": inline_contract,
            },
        }
    )
    workflow = _unlocked_workflow()
    source, sink = workflow.nodes
    workflow = replace(
        workflow,
        nodes=(
            replace(
                source,
                node_parameters={
                    **source.node_parameters,
                    "choice": {"x": 1},
                },
            ),
            sink,
        ),
    )

    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_commit_revision=2,
        catalog=catalog,
    )

    assert compiled.execution_plan.nodes[0].node_parameters["choice"] == {
        "x": 1
    }


def test_public_v2_mutation_failures_use_the_structured_error_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_app(frozen_catalog_override=_workflow_catalog())

    with TestClient(app) as client:
        protected_workflow = _unlocked_workflow().to_public()
        protected_workflow["workflow_id"] = "canonical-3gb1"
        protected = client.post(
            "/api/v2/projects/canonical-3gb1/workflow:commit",
            json={
                "workflow": protected_workflow,
            },
        )
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "mutation errors"},
        ).json()["id"]
        workflow = _unlocked_workflow().to_public()
        workflow["workflow_id"] = project_id
        workflow["nodes"][0]["node_parameters"]["nested"] = {
            "password": "must-not-persist",
        }
        credential = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow,
            },
        )
        alias_workflow = _unlocked_workflow().to_public()
        alias_workflow["workflow_id"] = project_id
        alias_workflow["nodes"][0]["node_parameters"]["nested"] = {
            "sessionCookie": "must-not-persist",
        }
        credential_alias = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": alias_workflow,
            },
        )
        persisted_draft = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft",
        )
        active_commit = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit",
        )
        missing_body = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
        )

    assert protected.status_code == 404
    validate_error(protected.json(), status=404)
    assert protected.json()["error"]["code"] == "project_not_found"
    assert missing_body.status_code == 400
    validate_error(missing_body.json(), status=400)
    assert missing_body.json()["error"]["code"] == "malformed_request"
    assert credential.status_code == 400
    validate_error(credential.json(), status=400)
    assert credential.json()["error"]["code"] == "malformed_request"
    assert credential_alias.status_code == 422
    validate_error(credential_alias.json(), status=422)
    assert credential_alias.json()["error"]["code"] == "compile_rejected"
    assert persisted_draft.status_code == 200
    validate_response(
        "project_workflow_draft",
        200,
        persisted_draft.json(),
    )
    assert persisted_draft.json()["draft_revision"] == 1
    assert persisted_draft.json()["workflow"] == alias_workflow
    assert active_commit.status_code == 404
    validate_error(active_commit.json(), status=404)
    assert (
        active_commit.json()["error"]["code"]
        == "workflow_commit_not_found"
    )


def test_public_commit_reports_an_inactive_exact_contract_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_app(frozen_catalog_override=_workflow_catalog())

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "inactive generation"},
        ).json()["id"]
        workflow = _unlocked_workflow().to_public()
        workflow["workflow_id"] = project_id
        workflow["nodes"][0]["node_type_version"] = "2.0.0"

        response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow,
            },
        )
        persisted_draft = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        )
        active_commit = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )

    assert response.status_code == 409
    validate_error(response.json(), status=409)
    assert response.json()["error"]["code"] == "inactive_generation"
    assert response.json()["error"]["details"]["issues"][0][
        "field_path"
    ] == ["nodes", 0, "node_type_version"]
    assert persisted_draft.status_code == 200
    assert persisted_draft.json()["draft_revision"] == 1
    assert persisted_draft.json()["workflow"] == workflow
    assert active_commit.status_code == 404


def test_public_commit_rejects_invalid_selector_scientific_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    catalog = _workflow_catalog()
    app = create_app(frozen_catalog_override=catalog)

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "stale unlocked reference"},
        ).json()["id"]
        workflow = _workflow_with_reference_generation(
            catalog,
            collection="observation_selectors",
            reference_field="metric",
            contract_version="2.1.0",
        ).to_public()
        workflow["workflow_id"] = project_id
        response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow,
            },
        )
        persisted_draft = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        )
        active_commit = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )

    assert response.status_code == 422
    validate_error(response.json(), status=422)
    assert response.json()["error"]["code"] == "compile_rejected"
    assert response.json()["error"]["details"]["issues"][0][
        "code"
    ] == "invalid_observation_selector"
    assert response.json()["error"]["details"]["issues"][0][
        "field_path"
    ] == [
        "observation_selectors",
        0,
        "candidate_input",
        "output_port",
    ]
    assert persisted_draft.status_code == 200
    assert persisted_draft.json()["draft_revision"] == 1
    assert persisted_draft.json()["workflow"] == workflow
    assert active_commit.status_code == 404


@pytest.mark.parametrize(
    ("version_field", "expected_path"),
    [
        ("node_type_version", ["nodes", 0, "node_type_version"]),
        ("binding_version", ["nodes", 0, "binding_version"]),
    ],
)
def test_public_draft_preserves_an_inactive_generation_until_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    version_field: str,
    expected_path: list[object],
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    catalog = _workflow_catalog()

    with TestClient(create_app(frozen_catalog_override=catalog)) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": f"inactive persisted {version_field}"},
        ).json()["id"]
        workflow = _unlocked_workflow().to_public()
        workflow["workflow_id"] = project_id
        workflow["nodes"][0][version_field] = "2.0.0"
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow/draft",
            json={
                "workflow": workflow,
            },
        )
        loaded = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        )
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow,
            },
        )

    assert saved.status_code == 200
    validate_response("save_project_workflow_draft", 200, saved.json())
    assert saved.json()["draft_revision"] == 1
    assert loaded.status_code == 200
    assert loaded.json() == saved.json()
    assert committed.status_code == 409
    validate_error(committed.json(), status=409)
    assert committed.json()["error"]["code"] == "inactive_generation"
    assert committed.json()["error"]["details"]["issues"][0][
        "field_path"
    ] == expected_path


def test_persisted_commit_cannot_start_after_catalog_generation_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    original_catalog = _workflow_catalog(source_algorithm="generation-a")
    active_catalog = _workflow_catalog(source_algorithm="generation-b")
    assert original_catalog.contract_digest != active_catalog.contract_digest

    with TestClient(
        create_app(frozen_catalog_override=original_catalog)
    ) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "persisted immutable commit"},
        ).json()["id"]
        unlocked = _unlocked_workflow().to_public()
        unlocked["workflow_id"] = project_id
        committed_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": unlocked,
            },
        )

    assert committed_response.status_code == 200
    committed = committed_response.json()
    validate_response("commit_project_workflow", 200, committed)

    with TestClient(
        create_app(frozen_catalog_override=active_catalog)
    ) as client:
        loaded = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "catalog-drift-start",
            },
        )

    assert loaded.status_code == 200
    validate_response(
        "project_active_workflow_commit",
        200,
        loaded.json(),
    )
    assert loaded.json() == committed
    assert started.status_code == 409
    validate_error(started.json(), status=409)
    assert started.json()["error"]["code"] == "contract_digest_mismatch"
    assert started.json()["error"]["details"]["issues"][0][
        "field_path"
    ] == ["contract_lock"]


def test_public_draft_commit_journey_is_revisioned_and_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_app(frozen_catalog_override=_workflow_catalog())

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "v2 authoring"},
        ).json()["id"]
        unlocked = _unlocked_workflow().to_public()
        unlocked["workflow_id"] = project_id

        saved_response = client.put(
            f"/api/v2/projects/{project_id}/workflow/draft",
            json={
                "workflow": unlocked,
            },
        )
        loaded_response = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        )
        committed_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": unlocked,
            },
        )
        active_response = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )
        receipt = committed_response.json()
        owner = app.state.workflow_authoring_v2
        committed = owner.load_active_commit(project_id)
        compiled = owner.require_compiled(
            project_id,
            workflow_commit_id=receipt["workflow_commit_id"],
        )

    assert saved_response.status_code == 200
    saved = saved_response.json()
    validate_response("save_project_workflow_draft", 200, saved)
    assert saved["draft_revision"] == 1
    assert saved["workflow"]["contract_lock"] == []
    assert loaded_response.json() == saved
    validate_response(
        "project_workflow_draft",
        200,
        loaded_response.json(),
    )
    assert committed_response.status_code == 200
    validate_response(
        "commit_project_workflow",
        200,
        receipt,
    )
    assert receipt["workflow_commit_revision"] == 1
    assert receipt["source_draft_revision"] == 2
    assert receipt["source_draft_digest"] == saved["draft_digest"]
    assert receipt["workflow_commit_id"] == receipt[
        "execution_plan_digest"
    ].replace("sha256:", "workflow-commit-")
    assert "execution_plan" not in receipt
    assert "nodes" not in receipt
    assert active_response.status_code == 200
    validate_response(
        "project_active_workflow_commit",
        200,
        active_response.json(),
    )
    assert active_response.json() == receipt
    assert committed.to_public() == receipt
    assert committed.locked_workflow.contract_lock
    assert (
        compiled.execution_plan.workflow_commit_revision
        == committed.workflow_commit_revision
    )
    assert (
        compiled.execution_plan.execution_plan_digest
        == committed.execution_plan_digest
    )
    assert (
        compiled.execution_plan.resolved_contracts
        == committed.locked_workflow.contract_lock
    )


def test_failed_commit_preserves_active_commit_and_submitted_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    factory_calls: list[str] = []
    catalog = _workflow_catalog(factory_calls=factory_calls)
    app = create_app(frozen_catalog_override=catalog)

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "failed replacement commit"},
        ).json()["id"]
        unlocked = _unlocked_workflow().to_public()
        unlocked["workflow_id"] = project_id
        active_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": unlocked,
            },
        )
        assert active_response.status_code == 200
        active = active_response.json()
        invalid = _unlocked_workflow().to_public()
        invalid["workflow_id"] = project_id
        invalid["edges"] = []
        failed_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": invalid,
            },
        )
        loaded_draft = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        )
        loaded_active = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )
        compiled = app.state.workflow_authoring_v2.require_compiled(
            project_id,
            workflow_commit_id=active["workflow_commit_id"],
        )

    assert failed_response.status_code == 422
    validate_error(failed_response.json(), status=422)
    assert failed_response.json()["error"]["code"] == "compile_rejected"
    assert failed_response.json()["error"]["details"]["issues"][0][
        "code"
    ] == "required_input_missing"
    assert failed_response.json()["error"]["details"]["issues"][0][
        "field_path"
    ] == ["nodes", 1]
    assert loaded_draft.status_code == 200
    assert loaded_draft.json()["draft_revision"] == 2
    assert loaded_draft.json()["workflow"] == invalid
    assert loaded_active.status_code == 200
    assert loaded_active.json() == active
    assert (
        compiled.execution_plan.execution_plan_digest
        == active["execution_plan_digest"]
    )
    assert factory_calls == []
