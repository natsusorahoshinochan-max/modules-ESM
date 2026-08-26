"""Public-seam tests for stable-ID v2 Workflow compilation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.declarations import (
    AvailabilityResult,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.model import (
    CatalogContract,
    FrozenCatalog,
)
from core.catalog.errors import (
    CatalogBuildError,
)
from core.catalog.port_contract import BehaviorReference
from tests.support.catalog import (
    binding_availability,
    catalog_contract,
    install_runtime,
)
from core.operation import (
    OperationContext,
    ReadinessResult,
)
from core.parameters.contract import (
    ParameterContractDefinitionError,
    admit_declarations,
)
from core.workflow.compiler import (
    CompilationRequest,
    compile,
)
from core.workflow.errors import WorkflowCompileError
from core.workflow.document import (
    WorkflowDocument,
    WorkflowDocumentError,
)
from core.workflow.plan import ExecutionPlan
from protein_workbench_public.workflow_codec import (
    decode_workflow_document,
    encode_workflow_commit_receipt,
    encode_workflow_document,
)
from tests.support.application import create_application
from tests.support.protocol import validate_error, validate_response


def _configure_application_data_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "application-data"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(data_root))


def _catalog_contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict,
) -> CatalogContract:
    resolved = {
        "schema_namespace": "protein-workbench-contract/v2",
        "contract_kind": contract_kind,
        "contract_id": contract_id,
        **descriptor,
    }
    try:
        return catalog_contract(
            contract_kind,
            contract_id,
            resolved,
        )
    except ParameterContractDefinitionError as error:
        raise CatalogBuildError(str(error)) from error


def _workflow_catalog(
    *,
    source_available: bool = True,
    sink_port_type_id: str = "text",
    source_output_multiplicity: str = "one",
    sink_input_multiplicity: str = "one",
    factory_calls: list[str] | None = None,
    source_node_parameter_overrides: dict | None = None,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    text = builtin.require_port_type("text")
    sink_port_type = builtin.require_port_type(sink_port_type_id)
    source_method = _catalog_contract(
        "method",
        "synthetic.source.method",
        {"algorithm_identity": {"name": "source"}},
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
            "execution_route": "direct",
            "deterministic": True,
            "cacheable": True,
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
                    "output_partition": "default",
                    "metric": metric.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "output",
                    "subject_port": "text",
                    "guaranteed_multiplicity": (
                        "one"
                        if source_output_multiplicity == "one"
                        else "one_or_more"
                    ),
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
            "execution_route": "direct",
            "deterministic": True,
            "cacheable": True,
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
    calls = factory_calls if factory_calls is not None else []

    def _factory(_context: OperationContext) -> object:
        calls.append("factory")
        raise AssertionError("Workflow compilation constructed an implementation")

    factories = {
        "synthetic.source.direct": ScientificOperationFactory(
            behavior=BehaviorReference(
                "synthetic.source/factory",
                {},
            ),
            build=_factory,
        ),
        "synthetic.sink.direct": ScientificOperationFactory(
            behavior=BehaviorReference(
                "synthetic.sink/factory",
                {},
            ),
            build=_factory,
        ),
    }
    readiness_declarations = {
        binding_id: ReadinessDeclaration(
            behavior=BehaviorReference(
                f"{binding_id}/readiness",
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
        binding_availability(
            source_binding,
            observed_at,
            (
                AvailabilityResult.available()
                if source_available
                else AvailabilityResult.unavailable(
                    "missing_runtime",
                    "Synthetic runtime is not installed",
                    retryable=False,
                )
            ),
        ),
        binding_availability(sink_binding, observed_at),
    )
    return FrozenCatalog(
        builtin.port_types,
        contracts=install_runtime(
            tuple(contracts),
            factories=factories,
            readiness=readiness_declarations,
        ),
        availability=availability,
        availability_observed_at=observed_at,
    )


def _workflow() -> WorkflowDocument:
    return decode_workflow_document(
        {
            "schema_version": "2.1.0",
            "workflow_id": "workflow-1",
            "nodes": [
                {
                    "node_id": "source",
                    "node_type_id": "synthetic.source",
                    "binding_id": "synthetic.source.direct",
                    "node_parameters": {"uppercase": True},
                    "binding_parameters": {"batch_size": 2},
                },
                {
                    "node_id": "sink",
                    "node_type_id": "synthetic.sink",
                    "binding_id": "synthetic.sink.direct",
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
            ]}
    )


def test_compile_returns_only_an_immutable_private_plan() -> None:
    catalog = _workflow_catalog()
    workflow = _workflow()

    compiled = compile(CompilationRequest(workflow), catalog)

    assert isinstance(compiled, ExecutionPlan)
    assert compiled.node_order == ("source", "sink")
    assert compiled.nodes[0].node_parameters == {
        "uppercase": True,
        "label": "default-label",
    }
    assert not hasattr(compiled, "receipt")
    assert not hasattr(compiled, "public_receipt")
    with pytest.raises(FrozenInstanceError):
        compiled.workflow_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        compiled.nodes[0].node_parameters["uppercase"] = False


def test_execution_plan_identity_excludes_runtime_handles() -> None:
    first_catalog = _workflow_catalog(factory_calls=[])
    second_catalog = _workflow_catalog(factory_calls=[])
    first_workflow = _workflow()
    second_workflow = _workflow()

    first = compile(CompilationRequest(first_workflow), first_catalog)
    second = compile(CompilationRequest(second_workflow), second_catalog)

    first_binding = first_catalog.require_contract(
        "binding",
        "synthetic.source.direct").definition
    second_binding = second_catalog.require_contract(
        "binding",
        "synthetic.source.direct").definition
    assert first_binding.factory is not second_binding.factory
    assert first_binding.readiness is not second_binding.readiness
    assert first == second


@pytest.mark.parametrize(
    ("field_name", "missing_id"),
    [
        ("node_type_id", "synthetic.missing"),
        ("binding_id", "synthetic.missing.direct"),
    ],
)
def test_unknown_selected_catalog_contract_reports_the_identity_field(
    field_name: str,
    missing_id: str,
) -> None:
    catalog = _workflow_catalog()
    workflow = _workflow()
    missing = replace(
        workflow.nodes[0],
        **{field_name: missing_id},
    )
    unresolved = replace(
        workflow,
        nodes=(missing, workflow.nodes[1]),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile(CompilationRequest(unresolved), catalog)

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
                        "binding_id": "synthetic.source.direct",
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
def test_workflow_wire_rejects_unsupported_fields_and_missing_binding(
    mutation: dict,
    expected_code: str,
) -> None:
    payload = encode_workflow_document(_workflow())
    payload.update(mutation)

    with pytest.raises(WorkflowDocumentError) as captured:
        decode_workflow_document(payload)

    assert captured.value.code == expected_code


def test_compile_rejects_an_undeclared_binding_parameter() -> None:
    catalog = _workflow_catalog()
    workflow = _workflow()
    source = replace(
        workflow.nodes[0],
        binding_parameters={
            **workflow.nodes[0].binding_parameters,
            "undeclared": "value",
        },
    )
    modified = replace(workflow, nodes=(source, workflow.nodes[1]))

    with pytest.raises(WorkflowCompileError) as captured:
        compile(CompilationRequest(modified), catalog)

    assert captured.value.code == "unknown_parameter"


def test_compile_validates_dag_binding_ownership_parameters_ports_and_availability() -> None:
    base = _workflow()
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
        with pytest.raises(WorkflowCompileError) as captured:
            compile(CompilationRequest(workflow), catalog)
        assert captured.value.code == expected_code


@pytest.mark.parametrize(
    ("parameters_field", "parameters", "expected_path"),
    (
        (
            "node_parameters",
            {},
            ("nodes", 0, "node_parameters", "uppercase"),
        ),
        (
            "binding_parameters",
            {"batch_size": 0},
            ("nodes", 0, "binding_parameters", "batch_size"),
        ),
    ),
)
def test_parameter_admission_errors_use_workflow_node_indexes(
    parameters_field: str,
    parameters: dict,
    expected_path: tuple[str | int, ...],
) -> None:
    catalog = _workflow_catalog()
    workflow = _workflow()
    source = replace(workflow.nodes[0], **{parameters_field: parameters})
    modified = replace(workflow, nodes=(source, workflow.nodes[1]))

    with pytest.raises(WorkflowCompileError) as captured:
        compile(CompilationRequest(modified), catalog)

    assert captured.value.field_path == expected_path
    assert captured.value.node_id == "source"


def test_nested_parameter_error_preserves_the_array_index_in_its_path() -> None:
    catalog = _workflow_catalog(
        source_node_parameter_overrides={
            "values": {
                "value_contract": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
        }
    )
    workflow = _workflow()
    source = replace(
        workflow.nodes[0],
        node_parameters={
            **workflow.nodes[0].node_parameters,
            "values": [1, "not-an-integer"],
        },
    )
    modified = replace(workflow, nodes=(source, workflow.nodes[1]))

    with pytest.raises(WorkflowCompileError) as captured:
        compile(CompilationRequest(modified), catalog)

    assert captured.value.field_path == (
        "nodes",
        0,
        "node_parameters",
        "values",
        1,
    )


def test_compile_keeps_an_unavailable_binding_for_cache_first_execution() -> None:
    catalog = _workflow_catalog(source_available=False)
    workflow = _workflow()

    plan = compile(CompilationRequest(workflow), catalog)

    assert plan.nodes[0].binding.contract_id == (
        "synthetic.source.direct"
    )
def test_compile_rejects_many_output_connected_to_one_input() -> None:
    catalog = _workflow_catalog(source_output_multiplicity="many")
    workflow = _workflow()

    with pytest.raises(WorkflowCompileError) as captured:
        compile(CompilationRequest(workflow), catalog)

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
    workflow = _workflow()

    compiled = compile(CompilationRequest(workflow), catalog)

    assert compiled.edges == workflow.edges


def test_compile_rejects_multiple_scalar_edges_to_one_input() -> None:
    catalog = _workflow_catalog()
    workflow = _workflow()
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
        compile(CompilationRequest(workflow), catalog)

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
    workflow = _workflow()
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
        compile(CompilationRequest(workflow), catalog)

    assert captured.value.code == "invalid_parameter"


def test_compile_rejects_undeclared_nested_fields_as_invalid_values(
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
    workflow = _workflow()
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
                            "undeclared": 1,
                        },
                    },
                },
            ),
            sink,
        ),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile(CompilationRequest(workflow), catalog)

    assert captured.value.code == "invalid_parameter"


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


def test_catalog_requires_explicit_nested_scientific_field_classification(
) -> None:
    with pytest.raises(CatalogBuildError):
        _workflow_catalog(
            source_node_parameter_overrides={
                "scientific_options": {
                    "value_contract": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "measurement": {"type": "string"},
                        },
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
    workflow = _workflow()
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

    compiled = compile(CompilationRequest(workflow), catalog)

    assert compiled.nodes[0].node_parameters["choice"] == value


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
    workflow = _workflow()
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

    compiled = compile(CompilationRequest(workflow), catalog)

    assert compiled.nodes[0].node_parameters["choice"] == {
        "x": 1
    }


def test_public_commit_rejects_invalid_selector_scientific_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_application_data_root(tmp_path, monkeypatch)
    catalog = _workflow_catalog()
    app = create_application(frozen_catalog_override=catalog)

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "invalid selector input"},
        ).json()["id"]
        workflow = encode_workflow_document(_workflow())
        workflow["observation_selectors"] = [
            {
                "selector_id": "selector-1",
                "candidate_input": {
                    "node_id": "source",
                    "output_port": "text",
                },
                "score_collection_input": {
                    "node_id": "source",
                    "output_port": "text",
                },
                "source_partition": "default",
                "metric": catalog.require_contract(
                    "metric", "synthetic.identity"
                ).reference(),
                "method": catalog.require_contract(
                    "method", "synthetic.source.method"
                ).reference(),
                "context_selector": {"kind": "intrinsic"},
                "match_cardinality": "exactly_one",
                "missing_policy": "error",
            }
        ]
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


def test_public_draft_commit_journey_uses_the_stable_commit_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_application_data_root(tmp_path, monkeypatch)
    app = create_application(frozen_catalog_override=_workflow_catalog())

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "v2 authoring"},
        ).json()["id"]
        workflow_payload = encode_workflow_document(_workflow())
        workflow_payload["workflow_id"] = project_id

        saved_response = client.put(
            f"/api/v2/projects/{project_id}/workflow/draft",
            json={
                "workflow": workflow_payload,
            },
        )
        loaded_response = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        )
        committed_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow_payload,
            },
        )
        active_response = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )
        receipt = committed_response.json()
        owner = app.state.workflow_authoring
        committed = owner.load_active_commit(project_id)
        compiled = owner.require_verified_commit(
            project_id,
            workflow_commit_id=receipt["workflow_commit_id"],
        )

    assert saved_response.status_code == 200
    saved = saved_response.json()
    validate_response("save_project_workflow_draft", 200, saved)
    assert saved["draft_revision"] == 1
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
    assert receipt["source_draft_revision"] == 2
    assert receipt["workflow_commit_id"].startswith("workflow-commit-")
    assert receipt["workflow"] == workflow_payload
    assert receipt["scientific_definitions"]
    assert "execution_plan" not in receipt
    assert "nodes" not in receipt
    assert active_response.status_code == 200
    validate_response(
        "project_active_workflow_commit",
        200,
        active_response.json(),
    )
    assert active_response.json() == receipt
    assert encode_workflow_commit_receipt(committed) == receipt
    assert compiled.commit == committed
    assert compiled.execution_plan.workflow_id == project_id
    assert compiled.execution_plan.scientific_definitions == (
        committed.scientific_definitions
    )


def test_failed_commit_preserves_active_commit_and_submitted_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_application_data_root(tmp_path, monkeypatch)
    factory_calls: list[str] = []
    catalog = _workflow_catalog(factory_calls=factory_calls)
    app = create_application(frozen_catalog_override=catalog)

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "failed replacement commit"},
        ).json()["id"]
        workflow_payload = encode_workflow_document(_workflow())
        workflow_payload["workflow_id"] = project_id
        active_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow_payload,
            },
        )
        assert active_response.status_code == 200
        active = active_response.json()
        invalid = encode_workflow_document(_workflow())
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
        compiled = app.state.workflow_authoring.require_verified_commit(
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
    assert compiled.commit.workflow_commit_id == active["workflow_commit_id"]
    assert compiled.execution_plan.workflow_id == project_id
    assert factory_calls == []
