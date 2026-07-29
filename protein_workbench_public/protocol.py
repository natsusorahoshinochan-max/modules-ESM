"""Load and identify the public protocol without importing backend internals."""

from __future__ import annotations

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

    if expected_type in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ProtocolValidationError(path, f"must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ProtocolValidationError(path, f"must be at most {maximum}")


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
    route = operation["route"]
    path_fields = re.findall(r"{([A-Za-z0-9_]+)}", route)
    for field in path_fields:
        route = route.replace(
            f"{{{field}}}",
            quote(str(payload[field]), safe=""),
        )
    body = {
        name: copy.deepcopy(value)
        for name, value in payload.items()
        if name not in path_fields
    }
    return PreparedRestRequest(
        method=operation["method"],
        route=route,
        json_body=body or None,
    )


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


def validate_artifact_response(
    metadata: Any,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    """Validate an Artifact Retrieval body against declared public metadata."""
    validate_schema("#/$defs/ArtifactResponseMetadata", metadata)
    artifact = metadata["artifact"]
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
