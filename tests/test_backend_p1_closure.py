"""Architecture and public emission gates for the P1 closure."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from core.parameters.model import AdmittedParameterValues
from core.project.manager import ProjectInputDescriptor, ProjectMeta
from core.scoring.selection import UtilityParameterFacts
from protein_workbench_public.http import emission
from protein_workbench_public.http.errors import (
    public_error_response,
)
from protein_workbench_public.http.project_routes import (
    _project_input_payload,
    _project_metadata_payload,
)
from protein_workbench_public.http.run_routes import (
    _replay_complete_payload,
    _replay_started_payload,
    _run_receipt_payload,
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
    ("operation_id", "_schema", "success_status"),
    _JSON_SUCCESS_CASES,
)
def test_each_json_success_operation_serializes_without_bundle_validation(
    monkeypatch: pytest.MonkeyPatch,
    operation_id: str,
    _schema: str,
    success_status: int,
) -> None:
    payload = {"operation_id": operation_id}

    def reject_validation(_reference: str, _value: Any) -> None:
        raise AssertionError("production emission must not validate the Bundle")

    monkeypatch.setattr(protocol, "validate_schema", reject_validation)
    response = emission.emit_rest_json_success(operation_id, payload)

    assert response.status_code == success_status
    assert json.loads(response.body) == payload


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


def test_rest_and_stream_emitters_do_not_revalidate_constructed_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_validation(_reference: str, _payload: Any) -> None:
        raise AssertionError("production emission must not validate the Bundle")

    monkeypatch.setattr(protocol, "validate_schema", reject_validation)
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


def test_structured_error_constructor_matches_bundle_without_emission_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = protocol.validate_schema
    assert set(protocol._STRUCTURED_ERROR_DETAILS_FIELDS) | {
        "selection_failed",
    } == set(protocol.load_bundle()["structured_errors"]["vocabulary"])

    def reject_validation(_reference: str, _payload: Any) -> None:
        raise AssertionError("production emission must not validate the Bundle")

    monkeypatch.setattr(protocol, "validate_schema", reject_validation)
    response = public_error_response(
        "run_not_found",
        "Run was not found",
        {
            "resource_kind": "run",
            "resource_id": "run-1",
            "ignored_internal_detail": True,
        },
    )
    assert response.status_code == 404
    response_payload = json.loads(response.body)
    assert response_payload["error"]["details"] == {
        "resource_kind": "run",
        "resource_id": "run-1",
    }
    original("#/$defs/StructuredErrorEnvelope", response_payload)

    _, error = protocol.project_structured_error(
        "node_execution_failed",
        "Node execution failed safely",
        {
            "exception_type": "RuntimeError",
            "cleanup_exception_types": ["PermissionError"],
        },
        "incident-1",
    )
    original(
        "#/$defs/RunEventStreamMessage",
        {"schema_namespace": "protein-workbench-public/v2", "error": error},
    )


def test_inline_public_response_constructors_match_bundle() -> None:
    timestamp = "2026-08-26T00:00:00+00:00"
    project = _project_metadata_payload(
        ProjectMeta(
            id="project-1",
            name="Project",
            created_at=timestamp,
            modified_at=timestamp,
        )
    )
    protocol.validate_schema("#/$defs/ProjectMetadata", project)

    project_input = _project_input_payload(
        "project-1",
        ProjectInputDescriptor(
            project_input_ref="input-1",
            filename="input.pdb",
            size=4,
            content_digest="sha256:" + "1" * 64,
        ),
    )
    protocol.validate_schema("#/$defs/ProjectInputPublication", project_input)

    receipt = _run_receipt_payload(
        project_id="project-1",
        run_id="run-1",
        workflow_commit_id="workflow-commit-" + "2" * 32,
        admitted_sequence=1,
        event_cursor="cursor-1",
    )
    protocol.validate_schema("#/$defs/RunReceipt", receipt)

    for event in (
        _replay_started_payload(
            project_id="project-1",
            run_id="run-1",
            sequence=0,
            cursor="cursor-0",
            emitted_at=timestamp,
            replay_through_cursor="cursor-1",
            after_sequence=None,
        ),
        _replay_complete_payload(
            project_id="project-1",
            run_id="run-1",
            sequence=1,
            cursor="cursor-1",
            emitted_at=timestamp,
        ),
    ):
        protocol.validate_schema("#/$defs/RunEventStreamMessage", event)


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
                        "contract_id": "protein.sequence"},
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
def test_binary_metadata_status_lookup_does_not_validate_bundle(
    monkeypatch: pytest.MonkeyPatch,
    operation_id: str,
    metadata: dict[str, Any],
    schema: str,
) -> None:
    original = protocol.validate_schema

    def reject_validation(_reference: str, _payload: Any) -> None:
        raise AssertionError("production emission must not validate the Bundle")

    monkeypatch.setattr(protocol, "validate_schema", reject_validation)
    status = protocol.binary_success_status(operation_id)
    assert status == 200
    original(schema, metadata)


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
        and node.func.id == "binary_success_status"
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
