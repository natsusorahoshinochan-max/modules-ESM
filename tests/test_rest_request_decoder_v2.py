"""Bundle-owned REST request source admission tests."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import pytest

import protein_workbench_public.protocol as public_protocol
from protein_workbench_public import (
    PreparedRestRequest,
    ProtocolValidationError,
    decode_rest_request,
    load_bundle,
    prepare_rest_request,
)


_BUNDLE = load_bundle()
_REST_OPERATION_IDS = tuple(sorted(_BUNDLE["rest_operations"]))


def _schema_example(schema: dict[str, Any]) -> Any:
    reference = schema.get("$ref")
    if reference is not None:
        name = reference.removeprefix("#/$defs/")
        named_examples = {
            "Digest": "sha256:" + "1" * 64,
            "Identifier": "identifier-1",
            "MediaType": "application/octet-stream",
            "NodeInstanceId": "node-1",
            "OpaqueCursor": "cursor-1",
            "OpaqueReference": "reference-1",
            "ProjectId": "project-1",
            "ProjectInputContentBase64": "cHJvdGVpbg==",
            "ProjectInputReference": "input-1",
            "RunId": "run-1",
            "SemanticVersion": "2.1.0",
            "WorkflowCommitId": "workflow-commit-" + "1" * 64,
        }
        if name in named_examples:
            return named_examples[name]
        return _schema_example(_BUNDLE["$defs"][name])
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "oneOf" in schema:
        return _schema_example(schema["oneOf"][0])
    if "anyOf" in schema:
        return _schema_example(schema["anyOf"][0])

    value_type = schema.get("type")
    if value_type == "object":
        properties = schema.get("properties", {})
        return {
            name: _schema_example(properties[name])
            for name in schema.get("required", [])
        }
    if value_type == "array":
        minimum = schema.get("minItems", 0)
        return [
            _schema_example(schema["items"])
            for _ in range(minimum)
        ]
    if value_type == "string":
        if schema.get("format") == "date-time":
            return "2026-08-03T00:00:00Z"
        return "value-1"
    if value_type == "integer":
        return schema.get("minimum", 0)
    if value_type == "number":
        return schema.get("minimum", 0.0)
    if value_type == "boolean":
        return True
    if value_type == "null":
        return None
    raise AssertionError(f"No example strategy for schema {schema!r}")


def _request_example(operation_id: str) -> dict[str, Any]:
    operation = _BUNDLE["rest_operations"][operation_id]
    schema_name = operation["request_schema"].removeprefix("#/$defs/")
    example = _schema_example(_BUNDLE["$defs"][schema_name])
    assert isinstance(example, dict)
    return example


def _route_fields(route: str) -> tuple[set[str], set[str]]:
    path_template, _, query_template = route.partition("?")
    return (
        set(re.findall(r"{([A-Za-z0-9_]+)}", path_template)),
        set(re.findall(r"{([A-Za-z0-9_]+)}", query_template)),
    )


def _render_expected_route(route: str, request: dict[str, Any]) -> str:
    path_template, separator, query_template = route.partition("?")

    def render(template: str) -> str:
        for field in re.findall(r"{([A-Za-z0-9_]+)}", template):
            template = template.replace(
                f"{{{field}}}", quote(str(request[field]), safe="")
            )
        return template

    rendered = render(path_template)
    if not separator:
        return rendered
    query_parts = []
    for part in query_template.split("&"):
        fields = re.findall(r"{([A-Za-z0-9_]+)}", part)
        if all(field in request for field in fields):
            query_parts.append(render(part))
    if query_parts:
        return f"{rendered}?{'&'.join(query_parts)}"
    return rendered


@pytest.mark.parametrize("explicit_body", [None, {}])
def test_bodyless_operation_distinguishes_absent_body_from_explicit_json(
    explicit_body: object,
) -> None:
    assert decode_rest_request("catalog_snapshot") == {}

    with pytest.raises(ProtocolValidationError, match="does not declare a body"):
        decode_rest_request("catalog_snapshot", json_body=explicit_body)


def test_rest_decoder_rejects_query_parameters_not_declared_by_the_route() -> None:
    with pytest.raises(ProtocolValidationError, match="not declared") as error:
        decode_rest_request(
            "catalog_snapshot",
            query_parameters={"legacy_cursor": "cursor-1"},
        )

    assert error.value.path == "$.legacy_cursor"


def test_rest_decoder_rejects_fields_repeated_across_wire_sources() -> None:
    bundle = load_bundle()
    start_operation = bundle["rest_operations"]["start_run"]
    start_schema = bundle["$defs"][
        start_operation["request_schema"].removeprefix("#/$defs/")
    ]
    start_body_field = sorted(
        set(start_schema["properties"]) - {"project_id"}
    )[0]
    cases = (
        (
            "artifact_retrieval",
            {
                "path_parameters": {"project_id": "project-1"},
                "query_parameters": {"project_id": "project-2"},
            },
            "project_id",
        ),
        (
            "start_run",
            {
                "path_parameters": {"project_id": "project-1"},
                "json_body": {"project_id": "project-2"},
            },
            "project_id",
        ),
        (
            "start_run",
            {
                "query_parameters": {start_body_field: "query-value"},
                "json_body": {start_body_field: "body-value"},
            },
            start_body_field,
        ),
    )

    for operation_id, sources, field in cases:
        with pytest.raises(
            ProtocolValidationError,
            match="multiple request sources",
        ) as error:
            decode_rest_request(operation_id, **sources)
        assert error.value.path == f"$.{field}"


def test_rest_route_query_declaration_controls_prepare_and_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_bundle()
    bundle["rest_operations"]["cancel_run"]["route"] += (
        "?after_sequence={after_sequence}"
    )
    monkeypatch.setattr(public_protocol, "_source_bundle", lambda: bundle)

    assert prepare_rest_request(
        "cancel_run",
        {"project_id": "project-1", "run_id": "run-1"},
    ) == PreparedRestRequest(
        method="POST",
        route="/api/v2/projects/project-1/runs/run-1:cancel",
        json_body=None,
    )
    assert prepare_rest_request(
        "cancel_run",
        {
            "project_id": "project-1",
            "run_id": "run-1",
            "after_sequence": "cursor/1",
            "reason": "operator request",
        },
    ) == PreparedRestRequest(
        method="POST",
        route=(
            "/api/v2/projects/project-1/runs/run-1:cancel"
            "?after_sequence=cursor%2F1"
        ),
        json_body={"reason": "operator request"},
    )
    assert decode_rest_request(
        "cancel_run",
        path_parameters={"project_id": "project-1", "run_id": "run-1"},
        query_parameters={"after_sequence": "cursor/1"},
        json_body={"reason": "operator request"},
    ) == {
        "project_id": "project-1",
        "run_id": "run-1",
        "after_sequence": "cursor/1",
        "reason": "operator request",
    }


def test_cancel_optional_object_accepts_absent_or_empty_but_rejects_null() -> None:
    path_parameters = {"project_id": "project-1", "run_id": "run-1"}
    expected = dict(path_parameters)

    assert decode_rest_request(
        "cancel_run",
        path_parameters=path_parameters,
    ) == expected
    assert decode_rest_request(
        "cancel_run",
        path_parameters=path_parameters,
        json_body={},
    ) == expected
    with pytest.raises(ProtocolValidationError, match="must be an object"):
        decode_rest_request(
            "cancel_run",
            path_parameters=path_parameters,
            json_body=None,
        )


def test_start_run_decoder_rejects_malformed_workflow_commit_identity() -> None:
    with pytest.raises(ProtocolValidationError, match="must match") as error:
        decode_rest_request(
            "start_run",
            path_parameters={"project_id": "project-1"},
            json_body={
                "workflow_commit_id": "workflow-commit-7",
                "client_request_id": "request-1",
            },
        )

    assert error.value.path == "$.workflow_commit_id"


@pytest.mark.parametrize("operation_id", _REST_OPERATION_IDS)
def test_every_rest_operation_round_trips_its_declared_wire_sources(
    operation_id: str,
) -> None:
    operation = _BUNDLE["rest_operations"][operation_id]
    request = _request_example(operation_id)
    path_fields, query_fields = _route_fields(operation["route"])
    path_parameters = {
        field: request[field] for field in path_fields if field in request
    }
    query_parameters = {
        field: request[field] for field in query_fields if field in request
    }
    json_body = {
        field: value
        for field, value in request.items()
        if field not in path_fields | query_fields
    }
    decode_arguments: dict[str, Any] = {
        "path_parameters": path_parameters,
        "query_parameters": query_parameters,
    }
    if json_body:
        decode_arguments["json_body"] = json_body

    assert decode_rest_request(operation_id, **decode_arguments) == request
    assert prepare_rest_request(operation_id, request) == PreparedRestRequest(
        method=operation["method"],
        route=_render_expected_route(operation["route"], request),
        json_body=json_body or None,
    )


_BODYLESS_OPERATION_IDS = tuple(
    operation_id
    for operation_id in _REST_OPERATION_IDS
    if not (
        set(
            _BUNDLE["$defs"][
                _BUNDLE["rest_operations"][operation_id]["request_schema"]
                .removeprefix("#/$defs/")
            ]["properties"]
        )
        - set().union(
            *_route_fields(
                _BUNDLE["rest_operations"][operation_id]["route"]
            )
        )
    )
)


@pytest.mark.parametrize("operation_id", _BODYLESS_OPERATION_IDS)
@pytest.mark.parametrize("explicit_body", [None, {}])
def test_every_bundle_bodyless_operation_rejects_any_explicit_json_body(
    operation_id: str,
    explicit_body: object,
) -> None:
    operation = _BUNDLE["rest_operations"][operation_id]
    request = _request_example(operation_id)
    path_fields, query_fields = _route_fields(operation["route"])

    with pytest.raises(ProtocolValidationError, match="does not declare a body"):
        decode_rest_request(
            operation_id,
            path_parameters={field: request[field] for field in path_fields},
            query_parameters={field: request[field] for field in query_fields},
            json_body=explicit_body,
        )


@pytest.mark.parametrize("operation_id", _REST_OPERATION_IDS)
def test_every_rest_operation_rejects_undeclared_query_parameters(
    operation_id: str,
) -> None:
    with pytest.raises(ProtocolValidationError, match="not declared") as error:
        decode_rest_request(
            operation_id,
            query_parameters={"undeclared_query": "value-1"},
        )

    assert error.value.path == "$.undeclared_query"
