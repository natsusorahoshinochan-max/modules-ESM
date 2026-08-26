"""Black-box response checks for public protocol acceptance tests."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

import rfc8785

from protein_workbench_public.protocol import (
    PUBLIC_PROTOCOL_NAMESPACE,
    ProtocolValidationError,
    artifact_content_disposition,
    load_bundle,
    validate_schema,
)


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ProtocolValidationError(path, message)


def _error_envelope(error: Any) -> dict[str, Any]:
    return {"schema_namespace": PUBLIC_PROTOCOL_NAMESPACE, "error": error}


def validate_event(payload: Any) -> None:
    validate_schema("#/$defs/RunEventEnvelope", payload)
    event = payload["event"]
    if "error" in event:
        validate_error(_error_envelope(event["error"]))


def validate_artifact_response(
    metadata: Any,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    validate_schema("#/$defs/ArtifactResponseMetadata", metadata)
    artifact = metadata["artifact"]
    disposition = artifact_content_disposition(artifact["filename"])
    _require(metadata["content_disposition"] == disposition,
             "$.content_disposition", f"must equal {disposition!r}")
    digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    _require(digest == artifact["content_digest"], "$.body",
             "content digest does not match artifact metadata")
    _require(len(body) == artifact["size"], "$.body",
             f"content size {len(body)} does not match {artifact['size']}")
    _validate_headers(
        headers,
        {
            "content-disposition": metadata["content_disposition"],
            "content-length": str(artifact["size"]),
            "content-type": artifact["media_type"],
            "digest": artifact["content_digest"],
        },
    )


def validate_typed_value_response(
    metadata: Any,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    validate_schema("#/$defs/TypedValueResponseMetadata", metadata)
    value = metadata["typed_value"]
    digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    _require(digest == value["value_content_digest"], "$.body",
             "content digest does not match Typed Output value metadata")
    _require(len(body) == value["size"], "$.body",
             "content size does not match Typed Output value metadata")
    _validate_headers(
        headers,
        {
            "content-length": str(value["size"]),
            "content-type": "application/json",
            "digest": value["value_content_digest"],
            "etag": f'"{value["value_content_digest"]}"',
            "x-port-content-digest": value["port_content_digest"],
            "x-port-type-kind": value["port_type"]["contract_kind"],
            "x-port-type-id": value["port_type"]["contract_id"],
            "x-value-count": str(value["value_count"]),
            "x-value-index": str(value["value_index"]),
            "x-value-manifest-reference": value["value_manifest_reference"],
        },
    )


def _validate_headers(
    headers: Mapping[str, str],
    expected_headers: Mapping[str, str],
) -> None:
    normalized = {name.lower(): value for name, value in headers.items()}
    for name, expected in expected_headers.items():
        observed = normalized.get(name)
        _require(observed == expected, f"$.headers.{name}",
                 f"must equal {expected!r}, got {observed!r}")


def validate_error(payload: Any, *, status: int | None = None) -> None:
    validate_schema("#/$defs/StructuredErrorEnvelope", payload)
    error = payload["error"]
    contract = load_bundle()["structured_errors"]
    definition = contract["vocabulary"].get(error["code"])
    if definition is None:
        raise ProtocolValidationError(
            "$.error.code",
            f"unknown structured-error code {error['code']!r}",
        )
    _require(status is None or status == definition["http_status"],
             "$.error.code",
             f"HTTP status {status} does not match {definition['http_status']}")
    _require(error["retryable"] is definition["retryable"],
             "$.error.retryable",
             f"must be {definition['retryable']!r} for {error['code']}")
    _require(
        len(rfc8785.dumps(error["details"]))
        <= contract["details_max_bytes"],
        "$.error.details",
        f"must be at most {contract['details_max_bytes']} canonical bytes",
    )
    try:
        validate_schema(definition["details_schema"], error["details"])
    except ProtocolValidationError as validation_error:
        suffix = validation_error.path.removeprefix("$")
        raise ProtocolValidationError(
            f"$.error.details{suffix}", validation_error.reason
        ) from validation_error


def validate_response(operation_id: str, status: int, payload: Any) -> None:
    operation = load_bundle()["rest_operations"][operation_id]
    mapping = operation["status_mapping"].get(
        str(status), operation["status_mapping"]["default"]
    )
    if mapping != "response":
        validate_error(payload, status=status)
        return
    response = operation["response"]
    _require(response["kind"] == "json", "$",
             f"{operation_id} is a binary response")
    validate_schema(response["schema"], payload)
    if operation_id == "run_projection" and "selection_error" in payload:
        validate_error(_error_envelope(payload["selection_error"]))
