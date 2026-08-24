"""Architecture and public emission gates for the P1 closure."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from core.parameters.model import AdmittedParameterValues
from core.scoring.selection import UtilityParameterFacts
from protein_workbench_public.http import emission
import protein_workbench_public.http.errors as http_errors
from protein_workbench_public.http.errors import (
    public_error_response,
    websocket_internal_error_boundary,
)
import protein_workbench_public.protocol as protocol


_ROOT = Path(__file__).resolve().parents[1]
_JSON_SUCCESS_CASES = tuple(
    (
        operation_id,
        operation["response"]["schema"],
        operation["response"]["success_status"],
    )
    for operation_id, operation in sorted(
        protocol.load_bundle()["rest_operations"].items()
    )
    if operation["response"]["kind"] == "json"
)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    imported.add(node.module)
                continue
            package = _module_name(path).split(".")
            if path.name != "__init__.py":
                package.pop()
            if node.level > 1:
                del package[-(node.level - 1) :]
            if node.module is not None:
                package.extend(node.module.split("."))
            base = ".".join(package)
            imported.add(base)
            if node.module is None:
                imported.update(
                    f"{base}.{alias.name}" for alias in node.names
                )
    return imported


def _production_imports(directory: str) -> set[str]:
    return {
        imported
        for path in (_ROOT / directory).rglob("*.py")
        for imported in _imported_modules(path)
    }


def test_closed_dependency_edges_have_no_forwarding_imports() -> None:
    assert not any(
        imported.startswith("core.execution")
        for imported in _production_imports("core/project")
    )
    assert not any(
        imported.startswith("core.parameters")
        for imported in _production_imports("core/scoring")
    )
    assert not any(
        imported.startswith("core.operation")
        for imported in _production_imports("protein_workbench_public")
    )

    candidate_imports = _imported_modules(_ROOT / "datatypes/candidate.py")
    exact_reference_imports = _imported_modules(
        _ROOT / "datatypes/exact_reference.py"
    )
    identifier_imports = _imported_modules(_ROOT / "datatypes/identifier.py")
    assert "datatypes.exact_reference" not in candidate_imports
    assert "datatypes.candidate" in exact_reference_imports
    assert not {
        "datatypes.candidate",
        "datatypes.exact_reference",
    }.intersection(identifier_imports)


def test_all_json_routes_and_websocket_sends_use_the_single_emitters() -> None:
    route_paths = tuple(
        _ROOT / "protein_workbench_public/http" / name
        for name in (
            "catalog_routes.py",
            "project_routes.py",
            "run_routes.py",
            "workflow_routes.py",
        )
    )
    emitted_operations: set[str] = set()
    for path in route_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "emit_rest_json_success"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                emitted_operations.add(node.args[0].value)
    expected = {
        operation_id
        for operation_id, operation in protocol.load_bundle()[
            "rest_operations"
        ].items()
        if operation["response"]["kind"] == "json"
    }
    assert len(expected) == 12
    assert emitted_operations == expected

    websocket_paths = (
        _ROOT / "protein_workbench_public/http/run_routes.py",
        _ROOT / "protein_workbench_public/http/errors.py",
    )
    stream_call_counts: list[int] = []
    for path in websocket_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        assert not any(
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_json"
            for node in calls
        )
        stream_call_counts.append(
            sum(
                isinstance(node.func, ast.Name)
                and node.func.id == "emit_run_event_stream_message"
                for node in calls
            )
        )
    assert stream_call_counts == [5, 1]


@pytest.mark.parametrize(
    ("operation_id", "schema", "success_status"),
    _JSON_SUCCESS_CASES,
)
def test_each_json_success_operation_uses_one_emitter_validation(
    monkeypatch: pytest.MonkeyPatch,
    operation_id: str,
    schema: str,
    success_status: int,
) -> None:
    validations: list[tuple[str, Any]] = []
    payload = {"operation_id": operation_id}

    def record_validation(reference: str, value: Any) -> None:
        validations.append((reference, value))

    monkeypatch.setattr(protocol, "validate_schema", record_validation)
    response = emission.emit_rest_json_success(operation_id, payload)

    assert response.status_code == success_status
    assert json.loads(response.body) == payload
    assert validations == [(schema, payload)]


def test_utility_parameter_facts_are_one_shallow_immutable_snapshot() -> None:
    admitted = AdmittedParameterValues(
        {"nested": {"values": [1, 2]}, "scalar": 3}
    )
    nested = admitted["nested"]

    facts = UtilityParameterFacts(admitted)

    assert dict(facts) == dict(admitted)
    assert facts["nested"] is nested
    with pytest.raises(TypeError):
        facts._values["additional"] = 4  # type: ignore[index]


def test_rest_and_stream_emitters_validate_once_before_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    references: list[str] = []
    original = protocol.validate_schema

    def counting_validate(reference: str, payload: Any) -> None:
        references.append(reference)
        original(reference, payload)

    monkeypatch.setattr(protocol, "validate_schema", counting_validate)
    project = {
        "schema_namespace": "protein-workbench-public/v2",
        "id": "project-1",
        "name": "Project",
        "created_at": "2026-08-24T00:00:00+00:00",
        "modified_at": "2026-08-24T00:00:00+00:00",
        "seed": False,
    }
    response = emission.emit_rest_json_success("create_project", project)
    assert response.status_code == 201
    assert references == ["#/$defs/ProjectMetadata"]

    references.clear()

    class Socket:
        def __init__(self) -> None:
            self.sent: list[Any] = []

        async def send_json(self, payload: Any) -> None:
            self.sent.append(payload)

    message = {
        "schema_namespace": "protein-workbench-public/v2",
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "retryable": False,
            "correlation_id": "incident-1",
            "details": {"incident_id": "incident-1"},
        },
    }
    socket = Socket()
    asyncio.run(emission.emit_run_event_stream_message(socket, message))  # type: ignore[arg-type]
    assert socket.sent == [message]
    assert references == ["#/$defs/RunEventStreamMessage"]


def test_invalid_success_projection_is_rejected_before_serialization() -> None:
    with pytest.raises(protocol.ProtocolValidationError):
        emission.emit_rest_json_success(
            "create_project",
            {"schema_namespace": "protein-workbench-public/v2"},
        )


def test_invalid_stream_projection_reaches_the_outer_internal_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Socket:
        def __init__(self) -> None:
            self.sent: list[Any] = []
            self.closed: list[int] = []

        async def send_json(self, payload: Any) -> None:
            self.sent.append(payload)

        async def close(self, *, code: int) -> None:
            self.closed.append(code)

    monkeypatch.setattr(
        http_errors,
        "report_public_internal_error",
        lambda _error, *, transport: f"incident-{transport.lower()}",
    )

    @websocket_internal_error_boundary
    async def emit_invalid(socket: Any) -> None:
        await emission.emit_run_event_stream_message(
            socket,
            {"schema_namespace": "protein-workbench-public/v2"},
        )

    socket = Socket()
    asyncio.run(emit_invalid(socket))

    assert socket.closed == [1011]
    assert len(socket.sent) == 1
    assert socket.sent[0]["error"]["code"] == "internal_error"


def test_structured_errors_use_one_details_and_one_enclosing_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    references: list[str] = []
    original = protocol.validate_schema

    def counting_validate(reference: str, payload: Any) -> None:
        references.append(reference)
        original(reference, payload)

    monkeypatch.setattr(protocol, "validate_schema", counting_validate)
    response = public_error_response(
        "run_not_found",
        "Run was not found",
        {"resource_kind": "run", "resource_id": "run-1"},
    )
    assert response.status_code == 404
    assert references == [
        "#/$defs/ResourceNotFoundDetails",
        "#/$defs/StructuredErrorEnvelope",
    ]

    references.clear()
    _, error = protocol.project_structured_error(
        "node_execution_failed",
        "Node execution failed safely",
        {
            "exception_type": "RuntimeError",
            "cleanup_exception_types": ["PermissionError"],
        },
        "incident-1",
    )
    protocol.admit_run_event_stream_message(
        {
            "schema_namespace": "protein-workbench-public/v2",
            "error": error,
        }
    )
    assert references == [
        "#/$defs/ExceptionErrorDetails",
        "#/$defs/RunEventStreamMessage",
    ]


@pytest.mark.parametrize(
    ("operation_id", "metadata", "schema"),
    (
        (
            "typed_value_retrieval",
            {
                "typed_value": {
                    "node_id": "node-1",
                    "output_port": "output",
                    "port_type": {
                        "contract_kind": "port_type",
                        "contract_id": "protein.sequence",
                        "contract_version": "1.0.0",
                        "contract_digest": "sha256:" + "1" * 64,
                    },
                    "port_content_digest": "sha256:" + "2" * 64,
                    "value_manifest_reference": "sha256:" + "3" * 64,
                    "value_index": 0,
                    "value_count": 1,
                    "value_content_digest": "sha256:" + "4" * 64,
                    "size": 3,
                }
            },
            "#/$defs/TypedValueResponseMetadata",
        ),
        (
            "artifact_retrieval",
            {
                "artifact": {
                    "artifact_reference": "artifact-1",
                    "artifact_kind": "standalone",
                    "node_id": "node-1",
                    "output_port": "output",
                    "media_type": "text/plain",
                    "filename": "result.txt",
                    "size": 3,
                    "content_digest": "sha256:" + "5" * 64,
                },
                "content_disposition": (
                    "attachment; filename*=UTF-8''result.txt"
                ),
            },
            "#/$defs/ArtifactResponseMetadata",
        ),
    ),
)
def test_binary_metadata_has_one_validation(
    monkeypatch: pytest.MonkeyPatch,
    operation_id: str,
    metadata: dict[str, Any],
    schema: str,
) -> None:
    references: list[str] = []
    original = protocol.validate_schema

    def counting_validate(reference: str, payload: Any) -> None:
        references.append(reference)
        original(reference, payload)

    monkeypatch.setattr(protocol, "validate_schema", counting_validate)
    status, admitted = protocol.admit_binary_response_metadata(
        operation_id,
        metadata,
    )
    assert status == 200
    assert admitted is metadata
    assert references == [schema]


@pytest.mark.parametrize(
    "function_name",
    ("public_v2_typed_value", "public_v2_artifact"),
)
def test_binary_routes_do_not_revalidate_body_or_headers(
    function_name: str,
) -> None:
    path = _ROOT / "protein_workbench_public/http/run_routes.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == function_name
    )
    calls = [
        node for node in ast.walk(function) if isinstance(node, ast.Call)
    ]
    assert sum(
        isinstance(node.func, ast.Name)
        and node.func.id == "admit_binary_response_metadata"
        for node in calls
    ) == 1
    for call in calls:
        argument_names = {
            node.id for node in ast.walk(call) if isinstance(node, ast.Name)
        }
        if argument_names.intersection({"body", "headers"}):
            assert isinstance(call.func, ast.Name)
            assert call.func.id == "Response"
    assert not any(
        {
            node.id
            for node in ast.walk(comparison)
            if isinstance(node, ast.Name)
        }.intersection({"body", "headers"})
        for comparison in ast.walk(function)
        if isinstance(comparison, ast.Compare)
    )
