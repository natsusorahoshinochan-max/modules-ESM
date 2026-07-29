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
    LazyImplementationFactory,
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
        contract_version="2.0.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
            "contract_version": "2.0.0",
            **descriptor,
        },
    )


def _workflow_catalog(
    *,
    source_available: bool = True,
    include_unreachable: bool = False,
    source_algorithm: str = "source",
    sink_port_type_id: str = "text",
    factory_calls: list[str] | None = None,
    source_node_parameter_overrides: dict | None = None,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    text = builtin.require_port_type("text", "2.0.0")
    sink_port_type = builtin.require_port_type(
        sink_port_type_id,
        "2.0.0",
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
                    "multiplicity": "one",
                }
            ],
            "node_parameters": {
                "uppercase": {
                    "type": "boolean",
                    "required": True,
                    "utility_transform": utility.reference(),
                },
                "label": {
                    "type": "string",
                    "default": "default-label",
                },
                **(source_node_parameter_overrides or {}),
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
                    "multiplicity": "one",
                }
            ],
            "outputs": [
                {
                    "name": "text",
                    "port_type": sink_port_type.reference(),
                    "required": True,
                    "multiplicity": "one",
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
                    "type": "integer",
                    "required": True,
                    "minimum": 1,
                }
            },
            "produced_observations": [
                {
                    "output_port": "text",
                    "metric": metric.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "guaranteed_multiplicity": "one",
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

    def _factory() -> object:
        calls.append("factory")
        raise AssertionError("Workflow compilation constructed an implementation")

    factories = {
        ("synthetic.source.direct", "2.0.0"): LazyImplementationFactory(
            behavior=BehaviorReference(
                "synthetic.source/factory",
                "2.0.0",
                {},
            ),
            build=_factory,
        ),
        ("synthetic.sink.direct", "2.0.0"): LazyImplementationFactory(
            behavior=BehaviorReference(
                "synthetic.sink/factory",
                "2.0.0",
                {},
            ),
            build=_factory,
        ),
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
    )


def _unlocked_workflow() -> WorkflowDocument:
    return parse_workflow_document(
        {
            "schema_version": "2.0.0",
            "workflow_id": "workflow-1",
            "nodes": [
                {
                    "node_id": "source",
                    "node_type_id": "synthetic.source",
                    "node_type_version": "2.0.0",
                    "binding_id": "synthetic.source.direct",
                    "binding_version": "2.0.0",
                    "node_parameters": {"uppercase": True},
                    "binding_parameters": {"batch_size": 2},
                },
                {
                    "node_id": "sink",
                    "node_type_id": "synthetic.sink",
                    "node_type_version": "2.0.0",
                    "binding_id": "synthetic.sink.direct",
                    "binding_version": "2.0.0",
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


def test_compile_returns_an_immutable_private_plan_and_compact_receipt() -> None:
    catalog = _workflow_catalog()
    workflow = relock_workflow(_unlocked_workflow(), catalog)

    compiled = compile_workflow(workflow, workflow_revision=2, catalog=catalog)

    assert isinstance(compiled, CompiledWorkflow)
    assert compiled.execution_plan.node_order == ("source", "sink")
    assert compiled.execution_plan.workflow_revision == 2
    assert compiled.execution_plan.resolved_contracts == workflow.contract_lock
    assert compiled.execution_plan.nodes[0].node_parameters == {
        "uppercase": True,
        "label": "default-label",
    }
    assert set(compiled.receipt) == {
        "accepted",
        "compile_id",
        "workflow_revision",
        "workflow_digest",
        "catalog_contract_digest",
        "contract_lock_digest",
        "execution_plan_digest",
        "issues",
    }
    assert compiled.receipt["accepted"] is True
    assert compiled.receipt["issues"] == ()
    validate_response(
        "workflow_compile",
        200,
        compiled.public_receipt(),
    )
    with pytest.raises(FrozenInstanceError):
        compiled.execution_plan.workflow_revision = 3  # type: ignore[misc]
    with pytest.raises(TypeError):
        compiled.execution_plan.nodes[0].node_parameters["uppercase"] = False
    with pytest.raises(TypeError):
        compiled.receipt["accepted"] = False


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
            "2.0.0",
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
        compile_workflow(mismatched, workflow_revision=2, catalog=catalog)

    assert captured.value.code == "contract_digest_mismatch"
    assert factory_calls == []


def test_unreachable_catalog_change_does_not_invalidate_the_lock() -> None:
    catalog_a = _workflow_catalog()
    catalog_b = _workflow_catalog(include_unreachable=True)
    workflow = relock_workflow(_unlocked_workflow(), catalog_a)

    compiled = compile_workflow(
        workflow,
        workflow_revision=2,
        catalog=catalog_b,
    )

    assert compiled.execution_plan.resolved_contracts == workflow.contract_lock
    assert catalog_a.contract_digest != catalog_b.contract_digest
    assert (
        compiled.receipt["catalog_contract_digest"]
        == catalog_b.contract_digest
    )


def test_reachable_contract_change_with_the_same_id_and_version_is_rejected() -> None:
    catalog_a = _workflow_catalog(source_algorithm="source-a")
    catalog_b = _workflow_catalog(source_algorithm="source-b")
    workflow = relock_workflow(_unlocked_workflow(), catalog_a)

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(workflow, workflow_revision=2, catalog=catalog_b)

    assert captured.value.code == "contract_digest_mismatch"


@pytest.mark.parametrize(
    ("field_name", "missing_id"),
    [
        ("node_type_id", "synthetic.missing"),
        ("binding_id", "synthetic.missing.direct"),
    ],
)
def test_missing_selected_catalog_contract_is_a_lock_mismatch(
    field_name: str,
    missing_id: str,
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
        contract_lock=(
            ContractLockEntry(
                "node_type",
                "synthetic.missing",
                "2.0.0",
                "sha256:" + ("a" * 64),
            ),
        ),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        compile_workflow(unresolved, workflow_revision=1, catalog=catalog)

    assert captured.value.code == "contract_digest_mismatch"


def test_explicit_relock_rejects_a_missing_catalog_contract() -> None:
    workflow = _unlocked_workflow()
    unresolved = replace(
        workflow,
        nodes=(
            replace(
                workflow.nodes[0],
                binding_id="synthetic.missing.direct",
            ),
            workflow.nodes[1],
        ),
    )

    with pytest.raises(WorkflowCompileError) as captured:
        relock_workflow(unresolved, _workflow_catalog())

    assert captured.value.code == "contract_digest_mismatch"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"schema_version": "1.0.0"}, "unsupported_schema_version"),
        (
            {
                "nodes": [
                    {
                        "node_id": "source",
                        "node_type_id": "synthetic.source",
                        "node_type_version": "latest",
                        "binding_id": "synthetic.source.direct",
                        "binding_version": "2.0.0",
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
                        "node_type_version": ">=2.0.0",
                        "binding_id": "synthetic.source.direct",
                        "binding_version": "2.0.0",
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
                        "node_type_version": "2.0.0",
                        "binding_version": "2.0.0",
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
                        "node_type_version": "2.0.0",
                        "binding_id": "synthetic.source.direct",
                        "binding_version": "2.0.0",
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
        compile_workflow(locked, workflow_revision=2, catalog=catalog)

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
            _workflow_catalog(sink_port_type_id="protein.sequence"),
            base,
        ),
        (
            "binding_unavailable",
            _workflow_catalog(source_available=False),
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
            compile_workflow(locked, workflow_revision=2, catalog=catalog)
        assert captured.value.code == expected_code


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
                    "count": {"type": "integer", "minimum": 1},
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
        source_node_parameter_overrides={"options": declaration}
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
            workflow_revision=2,
            catalog=catalog,
        )

    assert captured.value.code == "invalid_parameter"


@pytest.mark.parametrize(
    "forbidden_name",
    [
        "apiToken",
        "baseURL",
        "credentialHandle",
        "gpuDevice",
        "modelPath",
        "runtime.path",
        "auth_header",
    ],
)
def test_compile_rejects_nested_environment_configuration_fields(
    forbidden_name: str,
) -> None:
    catalog = _workflow_catalog(
        source_node_parameter_overrides={
            "scientific_options": {
                "type": "object",
                "additionalProperties": True,
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
            workflow_revision=2,
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
                "closed_contract": unsupported_contract,
            }
        )


@pytest.mark.parametrize(
    "environment_name",
    [
        "apiToken",
        "baseURL",
        "credentialHandle",
        "gpuDevice",
        "modelPath",
        "runtime.path",
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
        protected = client.put(
            "/api/v2/projects/canonical-3gb1/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": protected_workflow,
            },
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "origin policy"},
        ).json()["id"]
        workflow = _unlocked_workflow().to_public()
        workflow["workflow_id"] = project_id
        untrusted = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
            headers={"Origin": "https://untrusted.example"},
        )
        missing_body = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
        )

    for response in (protected, untrusted):
        assert response.status_code == 404
        validate_error(response.json(), status=404)
        assert (
            response.json()["error"]["code"]
            == "cross_scope_access_denied"
        )
    assert missing_body.status_code == 400
    validate_error(missing_body.json(), status=400)
    assert missing_body.json()["error"]["code"] == "malformed_request"


def test_public_save_load_relock_compile_journey_is_revisioned_and_exact(
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
            "/api/projects",
            json={"name": "v2 authoring"},
        ).json()["id"]
        unlocked = _unlocked_workflow().to_public()
        unlocked["workflow_id"] = project_id

        saved_response = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": unlocked,
            },
        )
        loaded_response = client.get(
            f"/api/v2/projects/{project_id}/workflow"
        )
        relocked_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": 1},
        )
        relocked = relocked_response.json()
        compiled_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": relocked["workflow_revision"],
                "workflow": relocked["workflow"],
            },
        )

    assert saved_response.status_code == 200
    saved = saved_response.json()
    validate_response("save_project_workflow", 200, saved)
    assert saved["workflow_revision"] == 1
    assert saved["workflow"]["contract_lock"] == []
    assert loaded_response.json() == saved
    validate_response(
        "project_workflow_snapshot",
        200,
        loaded_response.json(),
    )
    assert relocked_response.status_code == 200
    validate_response(
        "relock_project_workflow",
        200,
        relocked,
    )
    assert relocked["workflow_revision"] == 2
    assert relocked["workflow"]["contract_lock"]
    assert compiled_response.status_code == 200
    receipt = compiled_response.json()
    validate_response("workflow_compile", 200, receipt)
    assert receipt["workflow_revision"] == 2
    assert "execution_plan" not in receipt
    assert "nodes" not in receipt


def test_public_save_and_compile_never_silently_repair_a_stale_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    factory_calls: list[str] = []
    app = create_app(
        frozen_catalog_override=_workflow_catalog(
            source_available=False,
            factory_calls=factory_calls,
        )
    )

    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"name": "stale lock"},
        ).json()["id"]
        unlocked = _unlocked_workflow().to_public()
        unlocked["workflow_id"] = project_id
        client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": unlocked,
            },
        )
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": 1},
        ).json()
        stale = relocked["workflow"]
        stale["contract_lock"][0]["contract_digest"] = (
            "sha256:" + ("e" * 64)
        )
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 2,
                "workflow": stale,
            },
        ).json()
        response = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": 3,
                "workflow": stale,
            },
        )
        loaded = client.get(
            f"/api/v2/projects/{project_id}/workflow"
        ).json()

    assert saved["workflow_revision"] == 3
    assert saved["workflow"] == stale
    assert loaded == saved
    assert response.status_code == 409
    validate_error(response.json(), status=409)
    assert response.json()["error"]["code"] == "contract_digest_mismatch"
    assert factory_calls == []
