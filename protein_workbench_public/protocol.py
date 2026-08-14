"""Load and identify the public protocol without importing backend internals."""

from __future__ import annotations

import base64
import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import re
from typing import Any
from urllib.parse import quote

import rfc8785


PUBLIC_PROTOCOL_NAMESPACE = "protein-workbench-public/v2"
_RESOURCE_PACKAGE = "protein_workbench_public.resources.v2"
_RESOURCE_NAME = "bundle.json"
REST_BODY_ABSENT = object()
_CANONICAL_BASE64 = re.compile(
    r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z"
)
_BASE64_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
)


@dataclass(frozen=True, slots=True)
class PreparedRestRequest:
    """One wire request derived from a bundle operation."""

    method: str
    route: str
    json_body: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class PreparedEventStreamRequest:
    """One WebSocket request derived from the bundle stream contract."""

    transport: str
    route: str
    message_schema: str


class ProtocolValidationError(ValueError):
    """A public payload does not conform to the protocol bundle."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.reason = message
        super().__init__(f"{path}: {message}")


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


@lru_cache(maxsize=1)
def _source_bundle() -> dict[str, Any]:
    resource = files(_RESOURCE_PACKAGE).joinpath(_RESOURCE_NAME)
    parsed = json.loads(
        resource.read_bytes().decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Non-I-JSON numeric value: {value}")
        ),
    )
    if not isinstance(parsed, dict):
        raise ValueError("Public protocol bundle must be a JSON object")
    if parsed.get("schema_namespace") != PUBLIC_PROTOCOL_NAMESPACE:
        raise ValueError("Public protocol namespace does not match the loader")
    return parsed


def load_bundle() -> dict[str, Any]:
    """Return an isolated copy of the authoritative protocol definition."""
    return copy.deepcopy(_source_bundle())


@lru_cache(maxsize=1)
def bundle_bytes() -> bytes:
    """Return the RFC 8785 canonical UTF-8 representation of the bundle."""
    return rfc8785.dumps(_source_bundle())


@lru_cache(maxsize=1)
def bundle_digest() -> str:
    """Return the public SHA-256 identity of the canonical bundle."""
    return f"sha256:{hashlib.sha256(bundle_bytes()).hexdigest()}"


def _project_input_max_decoded_bytes() -> int:
    contract = _source_bundle().get("project_input_publication")
    if (
        not isinstance(contract, dict)
        or type(contract.get("max_decoded_bytes")) is not int
    ):
        raise ValueError(
            "Public protocol has no Project Input publication limit"
        )
    return contract["max_decoded_bytes"]


def encode_project_input_content(content: bytes) -> str:
    """Encode opaque Project Input bytes in the bundle's exact JSON form."""
    if type(content) is not bytes:
        raise ProtocolValidationError("$.content", "must be bytes")
    limit = _project_input_max_decoded_bytes()
    if len(content) > limit:
        raise ProtocolValidationError(
            "$.content",
            f"must contain at most {limit} bytes",
        )
    return base64.b64encode(content).decode("ascii")


def _validate_project_input_content(
    content_base64: str,
    *,
    path: str,
) -> None:
    if not isinstance(content_base64, str):
        raise ProtocolValidationError(
            path,
            "must be canonical base64 text",
        )
    if _CANONICAL_BASE64.fullmatch(content_base64) is None:
        raise ProtocolValidationError(
            path,
            "must be canonical base64 text",
        )
    padding = len(content_base64) - len(content_base64.rstrip("="))
    if (
        padding == 2
        and (_BASE64_ALPHABET.index(content_base64[-3]) & 0b1111) != 0
    ) or (
        padding == 1
        and (_BASE64_ALPHABET.index(content_base64[-2]) & 0b11) != 0
    ):
        raise ProtocolValidationError(
            path,
            "must be canonical base64 text",
        )
    decoded_size = (len(content_base64) // 4) * 3 - padding
    limit = _project_input_max_decoded_bytes()
    if decoded_size > limit:
        raise ProtocolValidationError(
            path,
            f"must decode to at most {limit} bytes",
        )


def decode_project_input_content(content_base64: str) -> bytes:
    """Decode only canonical RFC 4648 Project Input content."""
    _validate_project_input_content(
        content_base64,
        path="$.content_base64",
    )
    return base64.b64decode(content_base64)


def _resolve_schema(reference: str) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not reference.startswith(prefix):
        raise ValueError(f"Unsupported public protocol schema reference: {reference}")
    name = reference.removeprefix(prefix)
    schema = _source_bundle().get("$defs", {}).get(name)
    if not isinstance(schema, dict):
        raise ValueError(f"Unknown public protocol schema reference: {reference}")
    return schema


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise ValueError(f"Unsupported schema type: {expected}")


def _validate(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str,
) -> None:
    reference = schema.get("$ref")
    if reference is not None:
        _validate(value, _resolve_schema(reference), path=path)
        return

    alternatives = schema.get("oneOf")
    if alternatives is not None:
        failures: list[ProtocolValidationError] = []
        matches = 0
        for alternative in alternatives:
            try:
                _validate(value, alternative, path=path)
            except ProtocolValidationError as error:
                failures.append(error)
            else:
                matches += 1
        if matches != 1:
            if failures:
                detail = "; ".join(
                    dict.fromkeys(error.reason for error in failures)
                )
            else:
                detail = "matched multiple alternatives"
            raise ProtocolValidationError(
                path,
                f"must match exactly one schema alternative ({detail})",
            )
        return

    alternatives = schema.get("anyOf")
    if alternatives is not None:
        failures = []
        for alternative in alternatives:
            try:
                _validate(value, alternative, path=path)
            except ProtocolValidationError as error:
                failures.append(error)
            else:
                return
        raise ProtocolValidationError(
            path,
            f"must match a schema alternative ({failures[0].reason})",
        )

    if "const" in schema and value != schema["const"]:
        raise ProtocolValidationError(path, f"must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ProtocolValidationError(path, f"must be one of {schema['enum']!r}")

    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(value, expected_type):
        raise ProtocolValidationError(path, f"must be {expected_type}")

    if expected_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise ProtocolValidationError(
                path,
                f"missing required fields {missing!r}",
            )
        unexpected = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if unexpected and additional is False:
            raise ProtocolValidationError(
                path,
                f"unexpected fields {sorted(unexpected)!r}",
            )
        for name, item in value.items():
            item_schema = properties.get(name)
            if item_schema is None and isinstance(additional, dict):
                item_schema = additional
            if item_schema is not None:
                _validate(item, item_schema, path=f"{path}.{name}")

    if expected_type == "array":
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(value) < minimum:
            raise ProtocolValidationError(
                path,
                f"must contain at least {minimum} items",
            )
        if maximum is not None and len(value) > maximum:
            raise ProtocolValidationError(path, f"must contain at most {maximum} items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate(item, item_schema, path=f"{path}[{index}]")
        if schema.get("uniqueItems") is True:
            canonical_items = [rfc8785.dumps(item) for item in value]
            if len(canonical_items) != len(set(canonical_items)):
                raise ProtocolValidationError(path, "must contain unique items")

    if expected_type == "string":
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if minimum is not None and len(value) < minimum:
            raise ProtocolValidationError(
                path,
                f"must be at least {minimum} characters",
            )
        if maximum is not None and len(value) > maximum:
            raise ProtocolValidationError(path, f"must be at most {maximum} characters")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            raise ProtocolValidationError(path, f"must match {pattern!r}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ProtocolValidationError(
                    path,
                    "must be an ISO 8601 date-time",
                ) from error
            if parsed.tzinfo is None:
                raise ProtocolValidationError(path, "date-time must include a timezone")
        elif schema.get("format") == "canonical-base64":
            _validate_project_input_content(value, path=path)

    if expected_type in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if minimum is not None and value < minimum:
            raise ProtocolValidationError(path, f"must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ProtocolValidationError(path, f"must be at most {maximum}")
        if exclusive_minimum is not None and value <= exclusive_minimum:
            raise ProtocolValidationError(
                path,
                f"must be greater than {exclusive_minimum}",
            )
        if exclusive_maximum is not None and value >= exclusive_maximum:
            raise ProtocolValidationError(
                path,
                f"must be less than {exclusive_maximum}",
            )


def validate_schema(reference: str, payload: Any) -> None:
    """Validate one I-JSON payload against a named bundle schema."""
    try:
        rfc8785.dumps(payload)
    except (rfc8785.CanonicalizationError, UnicodeError) as error:
        raise ProtocolValidationError(
            "$",
            f"must contain only I-JSON values ({error})",
        ) from error
    _validate(payload, _resolve_schema(reference), path="$")


def _rest_operation(operation_id: str) -> dict[str, Any]:
    operation = _source_bundle().get("rest_operations", {}).get(operation_id)
    if not isinstance(operation, dict):
        raise ValueError(f"Unknown public protocol REST operation: {operation_id}")
    return operation


def prepare_rest_request(
    operation_id: str,
    payload: dict[str, Any],
) -> PreparedRestRequest:
    """Validate and map a combined request model to its declared wire shape."""
    validate_request(operation_id, payload)
    operation = _rest_operation(operation_id)
    path_template, separator, query_template = operation["route"].partition("?")
    path_fields = re.findall(r"{([A-Za-z0-9_]+)}", path_template)
    query_fields = re.findall(r"{([A-Za-z0-9_]+)}", query_template)

    def render(template: str) -> str:
        rendered = template
        for field in re.findall(r"{([A-Za-z0-9_]+)}", template):
            rendered = rendered.replace(
                f"{{{field}}}",
                quote(str(payload[field]), safe=""),
            )
        return rendered

    route = render(path_template)
    if separator:
        query_parts = []
        for part in query_template.split("&"):
            fields = re.findall(r"{([A-Za-z0-9_]+)}", part)
            if any(field not in payload for field in fields):
                continue
            query_parts.append(render(part))
        if query_parts:
            route = f"{route}?{'&'.join(query_parts)}"
    body = {
        name: copy.deepcopy(value)
        for name, value in payload.items()
        if name not in {*path_fields, *query_fields}
    }
    return PreparedRestRequest(
        method=operation["method"],
        route=route,
        json_body=body or None,
    )


def decode_rest_request(
    operation_id: str,
    *,
    path_parameters: Mapping[str, Any] | None = None,
    query_parameters: Mapping[str, Any] | None = None,
    json_body: Any = REST_BODY_ABSENT,
) -> dict[str, Any]:
    """Admit one REST request; omitted body differs from explicit JSON null."""
    operation = _rest_operation(operation_id)
    request_schema = _resolve_schema(operation["request_schema"])
    path_template, _, query_template = operation["route"].partition("?")
    path_fields = set(re.findall(r"{([A-Za-z0-9_]+)}", path_template))
    query_fields = set(re.findall(r"{([A-Za-z0-9_]+)}", query_template))
    body_fields = (
        set(request_schema.get("properties", {})) - path_fields - query_fields
    )
    path_payload = dict(path_parameters or {})
    query_payload = dict(query_parameters or {})
    body_was_supplied = json_body is not REST_BODY_ABSENT
    if not body_was_supplied:
        body_payload: dict[str, Any] = {}
    elif isinstance(json_body, Mapping):
        body_payload = dict(json_body)
    elif not body_fields:
        raise ProtocolValidationError("$", "operation does not declare a body")
    else:
        raise ProtocolValidationError("$", "request body must be an object")

    collisions = (
        set(path_payload).intersection(query_payload)
        | set(path_payload).intersection(body_payload)
        | set(query_payload).intersection(body_payload)
    )
    if collisions:
        field = sorted(collisions)[0]
        raise ProtocolValidationError(
            f"$.{field}",
            "field must not appear in multiple request sources",
        )

    unexpected_path_fields = set(path_payload) - path_fields
    if unexpected_path_fields:
        raise ProtocolValidationError(
            "$",
            (
                "path parameters must match declared route fields; unexpected "
                f"{sorted(unexpected_path_fields)!r}"
            ),
        )
    unexpected_query_fields = set(query_payload) - query_fields
    if unexpected_query_fields:
        field = sorted(unexpected_query_fields)[0]
        raise ProtocolValidationError(
            f"$.{field}",
            "query parameter is not declared by the operation route",
        )
    if body_was_supplied and not body_fields:
        raise ProtocolValidationError("$", "operation does not declare a body")
    source_owned_body_fields = (path_fields | query_fields).intersection(body_payload)
    if source_owned_body_fields:
        field = sorted(source_owned_body_fields)[0]
        raise ProtocolValidationError(
            f"$.{field}",
            "path/query-owned field must not appear in the request body",
        )
    combined = {
        **copy.deepcopy(path_payload),
        **copy.deepcopy(query_payload),
        **copy.deepcopy(body_payload),
    }
    validate_request(operation_id, combined)
    return combined


def prepare_run_event_stream_request(
    payload: dict[str, Any],
) -> PreparedEventStreamRequest:
    """Validate and map a Run Event Stream request from its bundle contract."""
    stream = _source_bundle().get("run_event_stream")
    if not isinstance(stream, dict):
        raise ValueError("Public protocol has no Run Event Stream contract")
    validate_schema(stream["request_schema"], payload)
    path_template, separator, query_template = stream["route"].partition("?")

    def render(template: str) -> str:
        rendered = template
        for field in re.findall(r"{([A-Za-z0-9_]+)}", template):
            rendered = rendered.replace(
                f"{{{field}}}",
                quote(str(payload[field]), safe=""),
            )
        return rendered

    route = render(path_template)
    if separator:
        query_parts = []
        for part in query_template.split("&"):
            fields = re.findall(r"{([A-Za-z0-9_]+)}", part)
            if any(field not in payload for field in fields):
                continue
            query_parts.append(render(part))
        if query_parts:
            route = f"{route}?{'&'.join(query_parts)}"
    return PreparedEventStreamRequest(
        transport=stream["transport"],
        route=route,
        message_schema=stream["message_schema"],
    )


def decode_run_event_stream_request(
    *,
    path_parameters: Mapping[str, Any],
    query_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Admit one Run Event Stream request through bundle-owned field sources."""
    stream = _source_bundle().get("run_event_stream")
    if not isinstance(stream, dict):
        raise ValueError("Public protocol has no Run Event Stream contract")
    path_template, _, query_template = stream["route"].partition("?")
    path_fields = set(re.findall(r"{([A-Za-z0-9_]+)}", path_template))
    query_fields = set(re.findall(r"{([A-Za-z0-9_]+)}", query_template))
    path_payload = dict(path_parameters)
    query_payload = dict(query_parameters or {})
    unexpected_path_fields = set(path_payload) - path_fields
    if unexpected_path_fields:
        raise ProtocolValidationError(
            "$",
            (
                "path parameters must match declared route fields; unexpected "
                f"{sorted(unexpected_path_fields)!r}"
            ),
        )
    collisions = path_fields.intersection(query_payload)
    if collisions:
        field = sorted(collisions)[0]
        raise ProtocolValidationError(
            f"$.{field}",
            "route-owned field must not appear in query parameters",
        )
    unexpected_query_fields = set(query_payload) - query_fields
    if unexpected_query_fields:
        field = sorted(unexpected_query_fields)[0]
        raise ProtocolValidationError(
            f"$.{field}",
            "query parameter is not declared by the event-stream route",
        )
    combined = {
        **copy.deepcopy(path_payload),
        **copy.deepcopy(query_payload),
    }
    validate_schema(stream["request_schema"], combined)
    return combined


def validate_request(operation_id: str, payload: Any) -> None:
    """Validate a path/query/body request model for one REST operation."""
    validate_schema(_rest_operation(operation_id)["request_schema"], payload)


def validate_event(payload: Any) -> None:
    """Validate one durable/replay Run Event Stream envelope."""
    validate_schema("#/$defs/RunEventEnvelope", payload)
    event = payload["event"]
    if "error" in event:
        validate_error(
            {
                "schema_namespace": PUBLIC_PROTOCOL_NAMESPACE,
                "error": event["error"],
            }
        )


def artifact_content_disposition(filename: str) -> str:
    """Return the Artifact filename's exact public response representation."""
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


def validate_artifact_response(
    metadata: Any,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    """Validate an Artifact Retrieval body against declared public metadata."""
    validate_schema("#/$defs/ArtifactResponseMetadata", metadata)
    artifact = metadata["artifact"]
    expected_disposition = artifact_content_disposition(
        artifact["filename"]
    )
    if metadata["content_disposition"] != expected_disposition:
        raise ProtocolValidationError(
            "$.content_disposition",
            f"must equal {expected_disposition!r}",
        )
    observed_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    if observed_digest != artifact["content_digest"]:
        raise ProtocolValidationError(
            "$.body",
            (
                "content digest does not match artifact metadata: "
                f"{observed_digest} != {artifact['content_digest']}"
            ),
        )
    if len(body) != artifact["size"]:
        raise ProtocolValidationError(
            "$.body",
            f"content size {len(body)} does not match {artifact['size']}",
        )
    normalized_headers = {name.lower(): value for name, value in headers.items()}
    expected_headers = {
        "content-disposition": metadata["content_disposition"],
        "content-length": str(artifact["size"]),
        "content-type": artifact["media_type"],
        "digest": artifact["content_digest"],
    }
    for name, expected in expected_headers.items():
        observed = normalized_headers.get(name)
        if observed != expected:
            raise ProtocolValidationError(
                f"$.headers.{name}",
                f"must equal {expected!r}, got {observed!r}",
            )


def validate_typed_value_response(
    metadata: Any,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    """Validate exact canonical Typed Output bytes and declared metadata."""
    validate_schema("#/$defs/TypedValueResponseMetadata", metadata)
    typed_value = metadata["typed_value"]
    observed_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    if observed_digest != typed_value["value_content_digest"]:
        raise ProtocolValidationError(
            "$.body",
            "content digest does not match Typed Output value metadata",
        )
    if len(body) != typed_value["size"]:
        raise ProtocolValidationError(
            "$.body",
            "content size does not match Typed Output value metadata",
        )
    normalized_headers = {name.lower(): value for name, value in headers.items()}
    expected_headers = {
        "content-length": str(typed_value["size"]),
        "content-type": "application/json",
        "digest": typed_value["value_content_digest"],
        "etag": f'"{typed_value["value_content_digest"]}"',
        "x-port-content-digest": typed_value["port_content_digest"],
        "x-port-type-kind": typed_value["port_type"]["contract_kind"],
        "x-port-type-id": typed_value["port_type"]["contract_id"],
        "x-port-type-version": typed_value["port_type"]["contract_version"],
        "x-port-type-digest": typed_value["port_type"]["contract_digest"],
        "x-value-count": str(typed_value["value_count"]),
        "x-value-index": str(typed_value["value_index"]),
        "x-value-manifest-reference": typed_value[
            "value_manifest_reference"
        ],
    }
    for name, expected in expected_headers.items():
        observed = normalized_headers.get(name)
        if observed != expected:
            raise ProtocolValidationError(
                f"$.headers.{name}",
                f"must equal {expected!r}, got {observed!r}",
            )


def validate_error(payload: Any, *, status: int | None = None) -> None:
    """Validate an error envelope and its code-specific closed details."""
    validate_schema("#/$defs/StructuredErrorEnvelope", payload)
    error = payload["error"]
    error_contract = _source_bundle()["structured_errors"]
    definition = error_contract["vocabulary"].get(error["code"])
    if definition is None:
        raise ProtocolValidationError(
            "$.error.code",
            f"unknown structured-error code {error['code']!r}",
        )
    if status is not None and status != definition["http_status"]:
        raise ProtocolValidationError(
            "$.error.code",
            (
                f"HTTP status {status} does not match "
                f"{definition['http_status']} for {error['code']}"
            ),
        )
    if error["retryable"] is not definition["retryable"]:
        raise ProtocolValidationError(
            "$.error.retryable",
            f"must be {definition['retryable']!r} for {error['code']}",
        )
    details_bytes = rfc8785.dumps(error["details"])
    if len(details_bytes) > error_contract["details_max_bytes"]:
        raise ProtocolValidationError(
            "$.error.details",
            f"must be at most {error_contract['details_max_bytes']} canonical bytes",
        )
    _validate(
        error["details"],
        _resolve_schema(definition["details_schema"]),
        path="$.error.details",
    )


def validate_response(operation_id: str, status: int, payload: Any) -> None:
    """Validate one JSON success response through its operation definition."""
    operation = _rest_operation(operation_id)
    mapping = operation["status_mapping"].get(
        str(status),
        operation["status_mapping"]["default"],
    )
    if mapping != "response":
        validate_error(payload, status=status)
        return
    response = operation["response"]
    if response["kind"] != "json":
        raise ProtocolValidationError(
            "$",
            f"{operation_id} is a binary response; validate its metadata instead",
        )
    validate_schema(response["schema"], payload)
    if (
        operation_id == "run_projection"
        and "selection_error" in payload
    ):
        validate_error(
            {
                "schema_namespace": PUBLIC_PROTOCOL_NAMESPACE,
                "error": payload["selection_error"],
            }
        )
