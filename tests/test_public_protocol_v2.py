"""Public, implementation-independent contract tests for protocol v2."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
import httpx

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from protein_workbench_public.bootstrap import create_application
from protein_workbench_public import (
    PUBLIC_PROTOCOL_NAMESPACE,
    PreparedEventStreamRequest,
    PreparedRestRequest,
    ProtocolValidationError,
    artifact_content_disposition,
    bundle_bytes,
    bundle_digest,
    decode_rest_request,
    decode_project_input_content,
    decode_run_event_stream_request,
    load_bundle,
    encode_project_input_content,
    prepare_run_event_stream_request,
    prepare_rest_request,
    validate_artifact_response,
    validate_typed_value_response,
    validate_error,
    validate_event,
    validate_request,
    validate_response,
    validate_schema,
)
from tests.public_protocol_acceptance_client import (
    PublicProtocolAcceptanceClient,
)


_WORKFLOW_COMMIT_ID = f"workflow-commit-{'7' * 64}"


def test_public_protocol_bundle_has_stable_canonical_identity() -> None:
    bundle = load_bundle()
    canonical = bundle_bytes()
    digest = bundle_digest()

    assert bundle["schema_namespace"] == "protein-workbench-public/v2"
    assert PUBLIC_PROTOCOL_NAMESPACE == bundle["schema_namespace"]
    assert bundle["schema_version"] == "2.3.0"
    assert bundle["identity"] == {
        "canonicalization": "RFC 8785",
        "character_encoding": "UTF-8",
        "digest_algorithm": "SHA-256",
        "digest_representation": "sha256:<64 lowercase hexadecimal digits>",
        "value_domain": "I-JSON",
    }
    assert canonical == bundle_bytes()
    assert digest == f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    assert bundle["project_input_publication"] == {
        "base64_alphabet": "RFC 4648 standard",
        "canonical_padding": "required",
        "max_decoded_bytes": 67_108_864,
    }
    assert bundle["$defs"]["ProjectInputContentBase64"]["maxLength"] == (
        89_478_488
    )


def test_bundle_closes_every_supported_rest_operation() -> None:
    bundle = load_bundle()
    operations = bundle["rest_operations"]

    assert set(operations) == {
        "artifact_retrieval",
        "cancel_run",
        "catalog_snapshot",
        "commit_project_workflow",
        "create_project",
        "publish_project_input",
        "project_active_workflow_commit",
        "project_input_metadata",
        "project_workflow_draft",
        "run_projection",
        "save_project_workflow_draft",
        "start_derived_run",
        "start_run",
        "typed_value_retrieval",
    }
    expected_transports = {
        "artifact_retrieval": (
            "GET",
            "/api/v2/projects/{project_id}/runs/{run_id}/artifacts/"
            "{artifact_reference}",
        ),
        "cancel_run": (
            "POST",
            "/api/v2/projects/{project_id}/runs/{run_id}:cancel",
        ),
        "catalog_snapshot": ("GET", "/api/v2/catalog"),
        "create_project": ("POST", "/api/v2/projects"),
        "commit_project_workflow": (
            "POST",
            "/api/v2/projects/{project_id}/workflow:commit",
        ),
        "project_active_workflow_commit": (
            "GET",
            "/api/v2/projects/{project_id}/workflow/active-commit",
        ),
        "project_input_metadata": (
            "GET",
            "/api/v2/projects/{project_id}/inputs/{project_input_ref}",
        ),
        "project_workflow_draft": (
            "GET",
            "/api/v2/projects/{project_id}/workflow/draft",
        ),
        "publish_project_input": (
            "POST",
            "/api/v2/projects/{project_id}/inputs",
        ),
        "run_projection": (
            "GET",
            "/api/v2/projects/{project_id}/runs/{run_id}",
        ),
        "save_project_workflow_draft": (
            "PUT",
            "/api/v2/projects/{project_id}/workflow/draft",
        ),
        "start_derived_run": (
            "POST",
            "/api/v2/projects/{project_id}/runs:derive",
        ),
        "start_run": ("POST", "/api/v2/projects/{project_id}/runs"),
        "typed_value_retrieval": (
            "GET",
            "/api/v2/projects/{project_id}/runs/{run_id}/outputs/"
            "{node_id}/{output_port}/values/{value_index}",
        ),
    }
    assert {
        operation_id: (operation["method"], operation["route"])
        for operation_id, operation in operations.items()
    } == expected_transports
    for operation in operations.values():
        assert set(operation) == {
            "method",
            "request_schema",
            "response",
            "route",
            "status_mapping",
        }
        assert operation["request_schema"].startswith("#/$defs/")
        assert operation["status_mapping"]["default"] == "structured_error"

    for name, schema in bundle["$defs"].items():
        if schema.get("type") == "object" and not schema.get("x-opaque-value"):
            assert schema.get("additionalProperties") is False, name


def test_typed_value_binary_metadata_closes_exact_headers_and_bytes() -> None:
    body = (
        b'{"port_type_id":"test.value","port_type_version":"1.0.0",'
        b'"schema_namespace":"protein-workbench-port-value/v2",'
        b'"value":"exact"}'
    )
    digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    metadata = {
        "typed_value": {
            "node_id": "node-1",
            "output_port": "result",
            "port_type": {
                "contract_kind": "port_type",
                "contract_id": "test.value",
                "contract_version": "1.0.0",
                "contract_digest": f"sha256:{'3' * 64}",
            },
            "port_content_digest": f"sha256:{'1' * 64}",
            "value_manifest_reference": f"sha256:{'2' * 64}",
            "value_index": 0,
            "value_count": 1,
            "value_content_digest": digest,
            "size": len(body),
        }
    }
    headers = {
        "Content-Length": str(len(body)),
        "Content-Type": "application/json",
        "Digest": digest,
        "ETag": f'"{digest}"',
        "X-Port-Content-Digest": f"sha256:{'1' * 64}",
        "X-Port-Type-Kind": "port_type",
        "X-Port-Type-Id": "test.value",
        "X-Port-Type-Version": "1.0.0",
        "X-Port-Type-Digest": f"sha256:{'3' * 64}",
        "X-Value-Count": "1",
        "X-Value-Index": "0",
        "X-Value-Manifest-Reference": f"sha256:{'2' * 64}",
    }

    validate_typed_value_response(metadata, headers, body)
    missing_port_digest = dict(headers)
    missing_port_digest.pop("X-Port-Type-Digest")
    with pytest.raises(ProtocolValidationError):
        validate_typed_value_response(metadata, missing_port_digest, body)
    with pytest.raises(ProtocolValidationError):
        validate_typed_value_response(metadata, headers, body + b"\n")


def test_acceptance_client_returns_validated_typed_value_metadata() -> None:
    body = b'{"value":"exact"}'
    digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    output = {
        "node_id": "node-1",
        "output_port": "result",
        "port_type": {
            "contract_kind": "port_type",
            "contract_id": "test.value",
            "contract_version": "1.0.0",
            "contract_digest": f"sha256:{'3' * 64}",
        },
        "content_digest": f"sha256:{'1' * 64}",
        "value_manifest_reference": f"sha256:{'2' * 64}",
        "value_count": 1,
    }
    metadata = {
        "typed_value": {
            "node_id": "node-1",
            "output_port": "result",
            "port_type": output["port_type"],
            "port_content_digest": output["content_digest"],
            "value_manifest_reference": output["value_manifest_reference"],
            "value_index": 0,
            "value_count": 1,
            "value_content_digest": digest,
            "size": len(body),
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == (
            "/api/v2/projects/project-1/runs/run-1/outputs/"
            "node-1/result/values/0"
        )
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Digest": digest,
                "ETag": f'"{digest}"',
                "X-Port-Content-Digest": output["content_digest"],
                "X-Port-Type-Kind": "port_type",
                "X-Port-Type-Id": "test.value",
                "X-Port-Type-Version": "1.0.0",
                "X-Port-Type-Digest": output["port_type"][
                    "contract_digest"
                ],
                "X-Value-Count": "1",
                "X-Value-Index": "0",
                "X-Value-Manifest-Reference": output[
                    "value_manifest_reference"
                ],
            },
        )

    with PublicProtocolAcceptanceClient(
        "http://backend.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.typed_value(
            {
                "project_id": "project-1",
                "run_id": "run-1",
                "node_id": "node-1",
                "output_port": "result",
                "value_index": 0,
            },
            output,
        ) == (metadata, body)


def test_bundle_schema_keyword_vocabulary_is_closed() -> None:
    def collect_keywords(schema: dict[str, Any]) -> set[str]:
        keywords = set(schema)
        for name in ("oneOf", "anyOf"):
            for alternative in schema.get(name, []):
                keywords.update(collect_keywords(alternative))
        properties = schema.get("properties", {})
        for property_schema in properties.values():
            keywords.update(collect_keywords(property_schema))
        items = schema.get("items")
        if isinstance(items, dict):
            keywords.update(collect_keywords(items))
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            keywords.update(collect_keywords(additional))
        return keywords

    observed: set[str] = set()
    for schema in load_bundle()["$defs"].values():
        observed.update(collect_keywords(schema))

    assert observed == {
        "$ref",
        "additionalProperties",
        "anyOf",
        "const",
        "enum",
        "exclusiveMinimum",
        "format",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "type",
        "uniqueItems",
        "x-opaque-value",
    }


def test_bundle_freezes_event_replay_close_and_error_vocabulary() -> None:
    bundle = load_bundle()
    stream = bundle["run_event_stream"]

    assert stream["transport"] == "websocket"
    assert stream["route"] == (
        "/api/v2/projects/{project_id}/runs/{run_id}/events"
        "?after_sequence={after_sequence}"
    )
    assert stream["request_schema"] == "#/$defs/RunEventStreamRequest"
    assert stream["message_schema"] == "#/$defs/RunEventStreamMessage"
    assert stream["event_union"] == [
        "engine_invocation_started",
        "engine_invocation_terminal",
        "node_attempt_started",
        "node_attempt_terminal",
        "node_disposition",
        "operation_attempt_started",
        "operation_attempt_terminal",
        "readiness_attested",
        "replay_complete",
        "replay_started",
        "run_admitted",
        "run_started",
        "selection_terminal",
        "run_terminal",
    ]
    assert stream["cursor_semantics"] == {
        "cursor": "opaque",
        "delivery": "at-most-once-per-connection",
        "resume": "exclusive",
        "restart": "rebuild-from-durable-ledger",
        "source": "durable-ledger-projection",
        "transition": "replay-then-live-without-gap-or-duplicate",
    }
    assert stream["close_behavior"] == {
        "1000": "after_run_terminal_or_client_close",
        "1008": "after_structured_policy_or_cursor_error",
        "1011": "after_structured_internal_error_when_safe",
    }

    errors = bundle["structured_errors"]
    assert errors["vocabulary_version"] == "2.3.0"
    assert errors["envelope_schema"] == "#/$defs/StructuredErrorEnvelope"
    assert errors["details_max_bytes"] == 16384
    assert errors["redaction_contract"] == {
        "stage": "before_persistence_or_transport",
        "unknown_details_fields": "reject",
        "values": "safe_bounded_public_values_only",
    }
    assert set(errors["vocabulary"]) == {
        "artifact_integrity_mismatch",
        "artifact_limit_exceeded",
        "artifact_not_found",
        "binding_unavailable",
        "cancellation_conflict",
        "compile_rejected",
        "contract_digest_mismatch",
        "cross_scope_access_denied",
        "evidence_unavailable",
        "inactive_generation",
        "internal_error",
        "invalid_cursor",
        "malformed_request",
        "node_execution_failed",
        "node_publication_failed",
        "project_not_found",
        "project_input_not_found",
        "protocol_mismatch",
        "readiness_rejected",
        "run_not_found",
        "selection_failed",
        "typed_output_not_found",
        "typed_value_integrity_mismatch",
        "unsupported_schema_version",
        "workflow_commit_identity_mismatch",
        "workflow_commit_not_found",
        "workflow_draft_not_found",
    }
    for code, definition in errors["vocabulary"].items():
        assert definition["code"] == code
        assert definition["http_status"] in {
            400,
            404,
            409,
            413,
            422,
            500,
            503,
        }
        assert isinstance(definition["retryable"], bool)
        assert definition["details_schema"].startswith("#/$defs/")


def test_failed_node_attempt_event_requires_exact_failure_origin() -> None:
    failed = {
        "type": "node_attempt_terminal",
        "node_attempt_id": "node-attempt-1",
        "status": "failed",
        "resolution": "executed",
        "failure_origin": "publication",
        "error": {
            "code": "node_publication_failed",
            "message": "Node result publication failed",
            "retryable": False,
            "correlation_id": "incident-publication",
            "details": {
                "node_id": "node-1",
                "publication_stage": "typed_value_object",
            },
        },
    }
    validate_schema("#/$defs/NodeAttemptTerminalEvent", failed)
    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/NodeAttemptTerminalEvent",
            {
                key: value
                for key, value in failed.items()
                if key != "failure_origin"
            },
        )
    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/NodeAttemptTerminalEvent",
            {
                key: value
                for key, value in failed.items()
                if key != "error"
            },
        )
    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/NodeAttemptTerminalEvent",
            {
                **failed,
                "status": "succeeded",
            },
        )


@pytest.mark.parametrize(
    ("failure_origin", "error"),
    (
        (
            "binding",
            {
                "code": "readiness_rejected",
                "message": "Selected Binding is not ready for this Run",
                "retryable": True,
                "correlation_id": "incident-binding",
                "details": {
                    "binding": {
                        "contract_kind": "binding",
                        "contract_id": "test.binding.local",
                        "contract_version": "2.1.0",
                        "contract_digest": "sha256:" + "1" * 64,
                    },
                    "reason_code": "model_unavailable",
                },
            },
        ),
        (
            "operation",
            {
                "code": "node_execution_failed",
                "message": "Node execution failed safely",
                "retryable": False,
                "correlation_id": "incident-operation",
                "details": {"exception_type": "PortValueError"},
            },
        ),
        (
            "publication",
            {
                "code": "node_publication_failed",
                "message": "Node result publication failed",
                "retryable": False,
                "correlation_id": "incident-publication",
                "details": {
                    "node_id": "node-1",
                    "publication_stage": "manifest",
                },
            },
        ),
    ),
)
def test_failed_node_attempt_event_closes_error_by_failure_origin(
    failure_origin: str,
    error: dict[str, object],
) -> None:
    event = {
        "type": "node_attempt_terminal",
        "node_attempt_id": "node-attempt-1",
        "status": "failed",
        "resolution": "executed",
        "failure_origin": failure_origin,
        "error": error,
    }
    validate_schema("#/$defs/NodeAttemptTerminalEvent", event)

    if failure_origin == "operation":
        with pytest.raises(ProtocolValidationError):
            validate_schema(
                "#/$defs/NodeAttemptTerminalEvent",
                {**event, "resolution": "cache_replayed"},
            )

    other_origin = "publication" if failure_origin == "operation" else "operation"
    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/NodeAttemptTerminalEvent",
            {**event, "failure_origin": other_origin},
        )

    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/NodeAttemptTerminalEvent",
            {
                **event,
                "error": {
                    **error,
                    "details": {
                        **error["details"],
                        "object_path": "/private/output/value.json",
                    },
                },
            },
        )


def test_engine_invocation_provenance_is_closed_and_residue_typed() -> None:
    event = {
        "type": "engine_invocation_started",
        "invocation_id": "invocation-1",
        "operation_attempt_id": "operation-1",
        "engine_role": "design_parent_0",
        "engine_identity": "sha256:" + "1" * 64,
    }
    projection = {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A", "B"],
        "provider_structure_chain_order": ["A", "B"],
        "provider_chain_order": ["B", "A"],
        "entries": [
            {
                "residue_id": "A:6",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "B:20",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 1,
            },
        ],
    }
    provenance = {"provider_residue_projection": projection}

    validate_schema("#/$defs/EngineInvocationStartedEvent", event)
    validate_schema(
        "#/$defs/EngineInvocationStartedEvent",
        {**event, "invocation_provenance": provenance},
    )

    validate_schema(
        "#/$defs/EngineInvocationStartedEvent",
        {
            **event,
            "invocation_provenance": {
                **provenance,
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 17,
                },
            },
        },
    )

    malformed_projections = (
        {**projection, "unexpected": True},
        {**projection, "position_semantics": "zero_based"},
        {**projection, "provider_chain_order": []},
        {**projection, "entries": []},
        {
            **projection,
            "entries": [
                {
                    "residue_id": "A:6",
                    "segment_index": 0,
                    "provider_chain_id": "A",
                    "provider_position": 0,
                }
            ],
        },
        {
            **projection,
            "entries": [
                {
                    "residue_id": "A:6",
                    "segment_index": 0,
                    "provider_chain_id": "A",
                    "provider_position": 1,
                    "unexpected": True,
                }
            ],
        },
    )
    for invalid_projection in malformed_projections:
        with pytest.raises(ProtocolValidationError):
            validate_schema(
                "#/$defs/EngineInvocationStartedEvent",
                {
                    **event,
                    "invocation_provenance": {
                        "provider_residue_projection": invalid_projection,
                    },
                },
            )
    for invalid_provenance in ({}, {**provenance, "unexpected": True}):
        with pytest.raises(ProtocolValidationError):
            validate_schema(
                "#/$defs/EngineInvocationStartedEvent",
                {**event, "invocation_provenance": invalid_provenance},
            )
    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/EngineInvocationStartedEvent",
            {**event, "engine_identity": "method-digest-1"},
        )


def test_project_input_filename_is_invocation_provenance_only() -> None:
    event = {
        "type": "engine_invocation_started",
        "invocation_id": "invocation-1",
        "operation_attempt_id": "operation-1",
        "engine_role": "primary",
        "engine_identity": "sha256:" + "1" * 64,
    }
    validate_schema(
        "#/$defs/EngineInvocationStartedEvent",
        {
            **event,
            "invocation_provenance": {
                "project_input_filename": "来源结构 A.pdb"
            },
        },
    )
    for malformed in (
        {"project_input_filename": ""},
        {"project_input_filename": "source.pdb", "project_input_ref": "x"},
    ):
        with pytest.raises(ProtocolValidationError):
            validate_schema(
                "#/$defs/EngineInvocationStartedEvent",
                {**event, "invocation_provenance": malformed},
            )


def test_public_validator_enforces_unique_bundle_items() -> None:
    projection = {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A", "A"],
        "provider_structure_chain_order": ["A"],
        "provider_chain_order": ["A"],
        "entries": [
            {
                "residue_id": "A:1",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 1,
            }
        ],
    }

    with pytest.raises(ProtocolValidationError, match="unique"):
        validate_schema(
            "#/$defs/ProviderResidueProjectionInvocationProvenance",
            projection,
        )


def test_provider_projection_supports_multiple_segments_per_workbench_chain() -> None:
    projection = {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A"],
        "provider_structure_chain_order": ["A", "B"],
        "provider_chain_order": ["B", "A"],
        "entries": [
            {
                "residue_id": "A:1",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "A:8",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 1,
            },
        ],
    }

    validate_schema(
        "#/$defs/ProviderResidueProjectionInvocationProvenance",
        projection,
    )


def test_engine_invocation_randomness_provenance_is_a_closed_union() -> None:
    event = {
        "type": "engine_invocation_started",
        "invocation_id": "invocation-1",
        "operation_attempt_id": "operation-1",
        "engine_role": "sample-0",
        "engine_identity": "sha256:" + "1" * 64,
    }
    exact_seed = {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": 17,
        }
    }
    provider_uncontrolled = {
        "effective_randomness": {
            "control": "provider_uncontrolled",
        }
    }

    for provenance in (exact_seed, provider_uncontrolled):
        validate_schema(
            "#/$defs/EngineInvocationStartedEvent",
            {**event, "invocation_provenance": provenance},
        )

    malformed = (
        {"effective_randomness": {"control": "exact_seed", "effective_seed": -1}},
        {
            "effective_randomness": {
                "control": "exact_seed",
                "effective_seed": 9_007_199_254_740_992,
            }
        },
        {
            "effective_randomness": {
                "control": "exact_seed",
                "effective_seed": True,
            }
        },
        {**exact_seed, "unexpected": True},
        {
            "effective_randomness": {
                "control": "provider_uncontrolled",
                "effective_seed": 17,
            }
        },
        {
            "effective_randomness": {
                "control": "unsupported_by_provider",
            }
        },
        {"effective_randomness": {"control": "exact_seed"}},
    )
    for provenance in malformed:
        with pytest.raises(ProtocolValidationError):
            validate_schema(
                "#/$defs/EngineInvocationStartedEvent",
                {**event, "invocation_provenance": provenance},
            )


def test_availability_and_schema_version_fail_closed() -> None:
    binding = {
        "contract_kind": "binding",
        "contract_id": "folding.simplefold",
        "contract_version": "2.1.0",
        "contract_digest": "sha256:" + "1" * 64,
    }
    validate_schema(
        "#/$defs/AvailabilitySnapshot",
        {
            "binding": binding,
            "observed_at": "2026-07-29T12:00:00+00:00",
            "available": False,
            "reason": {
                "code": "missing_checkpoint",
                "message": "Required checkpoint is absent",
                "retryable": False,
            },
        },
    )
    with pytest.raises(ProtocolValidationError, match="reason"):
        validate_schema(
            "#/$defs/AvailabilitySnapshot",
            {
                "binding": binding,
                "observed_at": "2026-07-29T12:00:00+00:00",
                "available": False,
            },
        )

    validate_error(
        {
            "schema_namespace": "protein-workbench-public/v2",
            "error": {
                "code": "unsupported_schema_version",
                "message": "Only v2 artifacts are supported",
                "retryable": False,
                "correlation_id": "incident-version",
                "details": {
                    "artifact_kind": "workflow",
                    "expected_schema_version": "2.1.0",
                    "received_schema_version": "1.0.0",
                },
            },
        },
        status=400,
    )
    validate_error(
        {
            "schema_namespace": "protein-workbench-public/v2",
            "error": {
                "code": "selection_failed",
                "message": "Workflow selection failed safely",
                "retryable": False,
                "correlation_id": "incident-selection",
                "details": {
                    "reason": (
                        "Utility Transform output must be within [0, 1]"
                    )
                },
            },
        },
        status=422,
    )
    validate_error(
        {
            "schema_namespace": "protein-workbench-public/v2",
            "error": {
                "code": "inactive_generation",
                "message": "Workflow uses an inactive exact contract",
                "retryable": False,
                "correlation_id": "incident-workflow-generation",
                "details": {
                    "issues": [
                        {
                            "code": "inactive_generation",
                            "severity": "error",
                            "message": "Requested 2.0.0; active is 2.1.0",
                            "field_path": [
                                "nodes",
                                0,
                                "node_type_version",
                            ],
                            "node_id": "source",
                        }
                    ]
                },
            },
        },
        status=409,
    )
    validate_error(
        {
            "schema_namespace": "protein-workbench-public/v2",
            "error": {
                "code": "inactive_generation",
                "message": "Run evidence belongs to an inactive Catalog",
                "retryable": False,
                "correlation_id": "incident-run-generation",
                "details": {
                    "artifact_kind": "run_evidence",
                    "expected_catalog_contract_digest": (
                        "sha256:" + "1" * 64
                    ),
                    "received_catalog_contract_digest": (
                        "sha256:" + "2" * 64
                    ),
                },
            },
        },
        status=409,
    )


def test_catalog_descriptor_and_node_disposition_are_closed() -> None:
    port_type = {
        "contract_kind": "port_type",
        "contract_id": "protein.pdb_string",
        "contract_version": "2.1.0",
        "contract_digest": "sha256:" + "2" * 64,
    }
    public_contract = {
        "reference": port_type,
        "descriptor": {
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": "port_type",
            "contract_id": "protein.pdb_string",
            "contract_version": "2.1.0",
            "validator": {
                "behavior_id": "pdb.validate",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "codec": {
                "behavior_id": "pdb.utf8",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "content_identity": {
                "behavior_id": "pdb.sha256",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
        },
    }
    validate_schema("#/$defs/PublicContract", public_contract)
    projection_behavior = {
        "behavior_id": "confidence.project",
        "behavior_version": "1.0.0",
        "parameters": {},
    }
    validate_schema(
        "#/$defs/PublicContract",
        {
            **public_contract,
            "descriptor": {
                **public_contract["descriptor"],
                "candidate_data_projection": projection_behavior,
                "scientific_axis_projection": projection_behavior,
                "observation_method_projection": projection_behavior,
            },
        },
    )
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_schema(
            "#/$defs/PublicContract",
            {
                **public_contract,
                "descriptor": {
                    **public_contract["descriptor"],
                    "private_factory": "modules.pdb:factory",
                },
            },
        )

    validate_schema(
        "#/$defs/NodeDisposition",
        {
            "node_id": "fold",
            "outcome": "succeeded",
            "resolution": "executed",
            "terminal_sequence": 8,
            "blocked_by": [],
        },
    )
    with pytest.raises(ProtocolValidationError, match="resolution"):
        validate_schema(
            "#/$defs/NodeDisposition",
            {
                "node_id": "fold",
                "outcome": "succeeded",
                "terminal_sequence": 8,
                "blocked_by": [],
            },
        )


def test_rest_payloads_are_validated_from_bundle_schemas() -> None:
    validate_request("create_project", {"name": "project one"})
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_request(
            "create_project",
            {"name": "project one", "legacy_id": "project-1"},
        )

    encoded = encode_project_input_content(b"\x00protein\xff")
    assert encoded == "AHByb3RlaW7/"
    assert decode_project_input_content(encoded) == b"\x00protein\xff"
    validate_request(
        "publish_project_input",
        {
            "project_id": "project-1",
            "filename": "input.pdb",
            "content_base64": encoded,
        },
    )
    for noncanonical in ("AHByb3RlaW7_", "AB==", "YQ"):
        with pytest.raises(ProtocolValidationError, match="canonical base64"):
            decode_project_input_content(noncanonical)
        with pytest.raises(ProtocolValidationError) as request_error:
            validate_request(
                "publish_project_input",
                {
                    "project_id": "project-1",
                    "filename": "input.pdb",
                    "content_base64": noncanonical,
                },
            )
        assert request_error.value.path == "$.content_base64"

    validate_request("catalog_snapshot", {})
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_request("catalog_snapshot", {"v1_fallback": True})

    request = {
        "project_id": "project-1",
        "workflow_commit_id": _WORKFLOW_COMMIT_ID,
        "client_request_id": "request-7",
    }
    validate_request("start_run", request)
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_request("start_run", {**request, "seed": 42})

    receipt = {
        "project_id": "project-1",
        "run_id": "run-7",
        "workflow_commit_id": _WORKFLOW_COMMIT_ID,
        "workflow_commit_revision": 7,
        "admitted_sequence": 1,
        "event_cursor": "cursor-1",
    }
    validate_response("start_run", 202, receipt)
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_response("start_run", 202, {**receipt, "status": "queued"})


def test_workflow_commit_receipt_can_represent_only_a_successful_commit() -> None:
    digest = f"sha256:{'a' * 64}"
    receipt = {
        "accepted": True,
        "workflow_commit_id": f"workflow-commit-{'b' * 64}",
        "workflow_commit_revision": 1,
        "source_draft_revision": 1,
        "source_draft_digest": digest,
        "workflow_digest": digest,
        "catalog_contract_digest": digest,
        "contract_lock_digest": digest,
        "execution_plan_digest": digest,
        "issues": [],
    }

    validate_schema("#/$defs/WorkflowCommit", receipt)
    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/WorkflowCommit",
            {**receipt, "accepted": False},
        )
    with pytest.raises(ProtocolValidationError):
        validate_schema(
            "#/$defs/WorkflowCommit",
            {
                **receipt,
                "issues": [
                    {
                        "code": "unexpected_issue",
                        "severity": "warning",
                        "message": "A commit receipt cannot carry issues",
                        "field_path": [],
                    }
                ],
            },
        )


def test_public_identifiers_use_nominal_bundle_schemas() -> None:
    valid_values = {
        "ProjectId": "project-1",
        "ProjectInputReference": "input-1",
        "RunId": "run-1",
        "NodeInstanceId": "node-1",
        "WorkflowCommitId": _WORKFLOW_COMMIT_ID,
    }
    for schema_name, valid in valid_values.items():
        reference = f"#/$defs/{schema_name}"
        validate_schema(reference, valid)
        invalid_values = (
            ("identity:1", "identity/1", "identity+1")
            if schema_name != "WorkflowCommitId"
            else (
                "workflow-commit-7",
                f"workflow-commit-{'A' * 64}",
                f"workflow-commit-{'7' * 63}",
                f"workflow-commit-{'7' * 65}",
            )
        )
        for invalid in invalid_values:
            with pytest.raises(ProtocolValidationError, match="must match"):
                validate_schema(reference, invalid)
    validate_schema("#/$defs/Identifier", "candidate:sha256:abc")
    validate_schema("#/$defs/Identifier", "A:42")

    bundle = load_bundle()
    nominal_fields = {
        "ProjectId": (
            ("ArtifactRetrievalRequest", "properties", "project_id"),
            ("CancelRunReceipt", "properties", "project_id"),
            ("CancelRunRequest", "properties", "project_id"),
            ("CrossScopeErrorDetails", "properties", "requested_project_id"),
            ("ProjectActiveWorkflowCommitRequest", "properties", "project_id"),
            ("ProjectInputMetadataRequest", "properties", "project_id"),
            ("ProjectInputPublication", "properties", "project_id"),
            ("ProjectMetadata", "properties", "id"),
            ("ProjectWorkflowDraft", "properties", "project_id"),
            ("ProjectWorkflowDraftRequest", "properties", "project_id"),
            ("PublishProjectInputRequest", "properties", "project_id"),
            ("RunEventEnvelope", "properties", "project_id"),
            ("RunEventStreamRequest", "properties", "project_id"),
            ("RunProjection", "properties", "project_id"),
            ("RunProjectionRequest", "properties", "project_id"),
            ("RunReceipt", "properties", "project_id"),
            ("SubmitProjectWorkflowRequest", "properties", "project_id"),
            ("TypedValueRetrievalRequest", "properties", "project_id"),
            ("StartDerivedRunRequest", "properties", "project_id"),
            ("StartRunRequest", "properties", "project_id"),
            ("WorkflowDocument", "properties", "workflow_id"),
        ),
        "ProjectInputReference": (
            (
                "ProjectInputPublication",
                "properties",
                "project_input_ref",
            ),
            (
                "ProjectInputMetadataRequest",
                "properties",
                "project_input_ref",
            ),
        ),
        "RunId": (
            ("ArtifactRetrievalRequest", "properties", "run_id"),
            ("CancelRunReceipt", "properties", "run_id"),
            ("CancelRunRequest", "properties", "run_id"),
            ("CrossScopeErrorDetails", "properties", "requested_run_id"),
            ("ResultMaterialization", "properties", "run_id"),
            ("ResultProducerProvenance", "properties", "producer_run_id"),
            ("RunEventEnvelope", "properties", "run_id"),
            ("RunEventStreamRequest", "properties", "run_id"),
            ("RunProjection", "properties", "derived_from_run_id"),
            ("RunProjection", "properties", "run_id"),
            ("RunProjectionRequest", "properties", "run_id"),
            ("RunReceipt", "properties", "run_id"),
            ("StartDerivedRunRequest", "properties", "source_run_id"),
            ("TypedValueRetrievalRequest", "properties", "run_id"),
        ),
        "NodeInstanceId": (
            ("BlockedNodeDisposition", "properties", "blocked_by", "items"),
            ("BlockedNodeDisposition", "properties", "node_id"),
            ("CandidateArtifactDescriptor", "properties", "node_id"),
            ("CompileIssue", "properties", "node_id"),
            ("NodeAttemptStartedEvent", "properties", "node_id"),
            ("NodeInstance", "properties", "node_id"),
            ("SelectionInput", "properties", "node_id"),
            ("SelectionResult", "properties", "selection_node_id"),
            ("StandaloneArtifactDescriptor", "properties", "node_id"),
            ("StartDerivedRunRequest", "properties", "node_ids", "items"),
            ("SucceededNodeDisposition", "properties", "blocked_by", "items"),
            ("SucceededNodeDisposition", "properties", "node_id"),
            ("TypedOutput", "properties", "node_id"),
            ("TypedValueDescriptor", "properties", "node_id"),
            ("TypedValueRetrievalRequest", "properties", "node_id"),
            ("UnsuccessfulNodeDisposition", "properties", "blocked_by", "items"),
            ("UnsuccessfulNodeDisposition", "properties", "node_id"),
            ("WorkflowEdge", "properties", "source_node_id"),
            ("WorkflowEdge", "properties", "target_node_id"),
        ),
        "WorkflowCommitId": (
            ("RunAdmittedEvent", "properties", "workflow_commit_id"),
            ("RunProjection", "properties", "workflow_commit_id"),
            ("RunReceipt", "properties", "workflow_commit_id"),
            ("StartRunRequest", "properties", "workflow_commit_id"),
            ("WorkflowCommit", "properties", "workflow_commit_id"),
            (
                "WorkflowCommitIdentityMismatchDetails",
                "properties",
                "workflow_commit_id",
            ),
        ),
    }
    for schema_name, paths in nominal_fields.items():
        for definition_name, *path in paths:
            observed = bundle["$defs"][definition_name]
            for part in path:
                observed = observed[part]
            assert observed == {"$ref": f"#/$defs/{schema_name}"}, (
                definition_name,
                path,
            )


def test_event_and_error_envelopes_share_bundle_validation() -> None:
    event = {
        "schema_namespace": "protein-workbench-public/v2",
        "project_id": "project-1",
        "run_id": "run-1",
        "sequence": 2,
        "cursor": "cursor-2",
        "emitted_at": "2026-07-29T12:00:00+00:00",
        "event": {
            "type": "run_started",
            "started_at": "2026-07-29T12:00:00+00:00",
        },
    }
    validate_event(event)
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_event({**event, "legacy_status": "running"})

    error = {
        "schema_namespace": "protein-workbench-public/v2",
        "error": {
            "code": "project_not_found",
            "message": "Project was not found",
            "retryable": False,
            "correlation_id": "incident-1",
            "details": {
                "resource_kind": "project",
                "resource_id": "project-1",
            },
        },
    }
    validate_error(error, status=404)
    with pytest.raises(ProtocolValidationError, match="HTTP status"):
        validate_error(error, status=500)
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_error(
            {
                **error,
                "error": {
                    **error["error"],
                    "details": {
                        **error["error"]["details"],
                        "private_path": "/tmp/secret",
                    },
                },
            },
            status=404,
        )


def test_artifact_response_validation_binds_metadata_headers_and_bytes() -> None:
    body = b"MODEL        1\\n"
    content_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    metadata = {
        "artifact": {
            "artifact_reference": "artifact_1",
            "artifact_kind": "standalone",
            "node_id": "export",
            "output_port": "structure",
            "media_type": "chemical/x-pdb",
            "filename": "structure.pdb",
            "size": len(body),
            "content_digest": content_digest,
        },
        "content_disposition": (
            "attachment; filename*=UTF-8''structure.pdb"
        ),
    }
    headers = {
        "Content-Disposition": metadata["content_disposition"],
        "Content-Length": str(len(body)),
        "Content-Type": "chemical/x-pdb",
        "Digest": content_digest,
    }

    validate_artifact_response(metadata, headers, body)
    without_filename = deepcopy(metadata)
    without_filename["artifact"].pop("filename")
    with pytest.raises(ProtocolValidationError, match="filename"):
        validate_artifact_response(without_filename, headers, body)
    with pytest.raises(ProtocolValidationError, match="content digest"):
        validate_artifact_response(metadata, headers, body + b"TAMPERED")
    with pytest.raises(ProtocolValidationError, match="candidate_id"):
        validate_artifact_response(
            {
                **metadata,
                "artifact": {
                    **metadata["artifact"],
                    "artifact_kind": "candidate",
                },
            },
            headers,
            body,
        )


@pytest.mark.parametrize(
    ("filename", "expected"),
    (
        (
            'structure "alpha".pdb',
            "attachment; filename*=UTF-8''structure%20%22alpha%22.pdb",
        ),
        (
            "来源结构.pdb",
            (
                "attachment; filename*=UTF-8''"
                "%E6%9D%A5%E6%BA%90%E7%BB%93%E6%9E%84.pdb"
            ),
        ),
    ),
)
def test_artifact_content_disposition_encodes_exact_utf8_filename(
    filename: str,
    expected: str,
) -> None:
    assert artifact_content_disposition(filename) == expected


def test_artifact_response_accepts_maximum_length_utf8_filename() -> None:
    body = b"MODEL        1\n"
    filename = "蛋" * 512
    content_disposition = artifact_content_disposition(filename)
    metadata = {
        "artifact": {
            "artifact_reference": "artifact_1",
            "artifact_kind": "standalone",
            "node_id": "export",
            "output_port": "structure",
            "media_type": "chemical/x-pdb",
            "filename": filename,
            "size": len(body),
            "content_digest": (
                f"sha256:{hashlib.sha256(body).hexdigest()}"
            ),
        },
        "content_disposition": content_disposition,
    }
    headers = {
        "Content-Disposition": content_disposition,
        "Content-Length": str(len(body)),
        "Content-Type": "chemical/x-pdb",
        "Digest": metadata["artifact"]["content_digest"],
    }

    validate_artifact_response(metadata, headers, body)


def test_backend_serves_the_authoritative_bundle_without_a_v1_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    discovery = load_bundle()["bundle_discovery"]

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        response = client.get(discovery["route"])

    assert discovery == {
        "digest_header": "Digest",
        "media_type": "application/vnd.protein-workbench.protocol+json",
        "method": "GET",
        "route": "/api/v2/protocol",
    }
    assert response.status_code == 200
    assert response.content == bundle_bytes()
    assert response.headers["content-type"] == discovery["media_type"]
    assert response.headers["digest"] == bundle_digest()
    assert "/api/" not in discovery["route"].replace("/api/v2/", "")


def test_backend_rejects_undeclared_discovery_and_catalog_wire_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        responses = (
            client.get("/api/v2/protocol?legacy=1"),
            client.request("GET", "/api/v2/protocol", content=b"{}"),
            client.get("/api/v2/catalog?legacy=1"),
            client.request("GET", "/api/v2/catalog", content=b"{}"),
            client.request(
                "POST",
                "/api/v2/projects/project-1/runs/run-1:cancel",
                content=b'{"after_sequence":1e400}',
                headers={"content-type": "application/json"},
            ),
        )

    for response in responses:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "malformed_request"


def test_backend_public_route_inventory_equals_the_bundle() -> None:
    bundle = load_bundle()
    expected_http = {
        (operation["method"], operation["route"])
        for operation in bundle["rest_operations"].values()
    }
    discovery = bundle["bundle_discovery"]
    expected_http.add((discovery["method"], discovery["route"]))
    expected_websocket = {
        bundle["run_event_stream"]["route"].partition("?")[0]
    }
    observed_http: set[tuple[str, str]] = set()
    observed_websocket: set[str] = set()
    framework_documentation_routes = {
        "/docs",
        "/docs/oauth2-redirect",
        "/openapi.json",
        "/redoc",
    }
    for route in create_application(_install_canonical_seed=False).routes:
        path = getattr(route, "path", "")
        if path in framework_documentation_routes:
            continue
        methods = getattr(route, "methods", None)
        if methods:
            observed_http.update((method, path) for method in methods)
        else:
            observed_websocket.add(path)

    assert observed_http == expected_http
    assert observed_websocket == expected_websocket


def test_project_and_immutable_input_publication_use_only_bundle_operations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as http:
        def public_request(
            operation_id: str,
            request_model: dict[str, Any],
        ) -> dict[str, Any]:
            prepared = prepare_rest_request(operation_id, request_model)
            response = http.request(
                prepared.method,
                prepared.route,
                json=prepared.json_body,
            )
            payload = response.json()
            validate_response(operation_id, response.status_code, payload)
            return payload

        project = public_request("create_project", {"name": "public project"})
        publication = public_request(
            "publish_project_input",
            {
                "project_id": project["id"],
                "filename": "source.pdb",
                "content_base64": encode_project_input_content(b"ATOM\n"),
            },
        )

        invalid = http.post(
            f"/api/v2/projects/{project['id']}/inputs",
            json={"filename": "source.pdb", "content_base64": "AB=="},
        )
        legacy_project = http.post(
            "/api/projects",
            json={"name": "legacy"},
        )

    assert project["schema_namespace"] == PUBLIC_PROTOCOL_NAMESPACE
    assert set(project) == {
        "schema_namespace",
        "id",
        "name",
        "created_at",
        "modified_at",
        "seed",
    }
    assert project["name"] == "public project"
    assert project["seed"] is False
    assert publication == {
        "schema_namespace": PUBLIC_PROTOCOL_NAMESPACE,
        "project_id": project["id"],
        "filename": "source.pdb",
        "project_input_ref": publication["project_input_ref"],
        "size": 5,
        "content_digest": (
            "sha256:" + hashlib.sha256(b"ATOM\n").hexdigest()
        ),
    }
    assert re.fullmatch(r"input-[0-9a-f]{32}", publication["project_input_ref"])
    assert invalid.status_code == 400
    validate_response(
        "publish_project_input",
        invalid.status_code,
        invalid.json(),
    )
    assert invalid.json()["error"]["details"]["field_path"] == [
        "content_base64"
    ]
    assert legacy_project.status_code == 404


def test_project_input_metadata_recovers_filename_after_backend_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    def public_request(
        http: TestClient,
        operation_id: str,
        request_model: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        prepared = prepare_rest_request(operation_id, request_model)
        response = http.request(
            prepared.method,
            prepared.route,
            json=prepared.json_body,
        )
        payload = response.json()
        validate_response(operation_id, response.status_code, payload)
        return response.status_code, payload

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as first_backend:
        _, project = public_request(
            first_backend,
            "create_project",
            {"name": "restart provenance"},
        )
        _, publication = public_request(
            first_backend,
            "publish_project_input",
            {
                "project_id": project["id"],
                "filename": "来源结构 A.pdb",
                "content_base64": encode_project_input_content(b"ATOM\n"),
            },
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as restarted_backend:
        status, recovered = public_request(
            restarted_backend,
            "project_input_metadata",
            {
                "project_id": project["id"],
                "project_input_ref": publication["project_input_ref"],
            },
        )
        missing_status, missing = public_request(
            restarted_backend,
            "project_input_metadata",
            {
                "project_id": project["id"],
                "project_input_ref": "input-missing",
            },
        )

    assert status == 200
    assert recovered == publication
    assert missing_status == 404
    assert missing["error"]["code"] == "project_input_not_found"
    assert missing["error"]["details"] == {
        "resource_kind": "project_input",
        "resource_id": "input-missing",
    }


def test_backend_rejects_route_owned_fields_in_every_json_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": "project-2",
        "nodes": [],
        "edges": [],
        "contract_lock": [],
    }
    cases = {
        "save_project_workflow_draft": (
            "PUT",
            "/api/v2/projects/project-1/workflow/draft",
            {
                "project_id": "project-2",
                "workflow": workflow,
            },
        ),
        "commit_project_workflow": (
            "POST",
            "/api/v2/projects/project-1/workflow:commit",
            {
                "project_id": "project-2",
                "workflow": workflow,
            },
        ),
        "start_run": (
            "POST",
            "/api/v2/projects/project-1/runs",
            {
                "project_id": "project-2",
                "workflow_commit_id": _WORKFLOW_COMMIT_ID,
                "client_request_id": "request-1",
            },
        ),
        "cancel_run": (
            "POST",
            "/api/v2/projects/project-1/runs/run-1:cancel",
            {"project_id": "project-2"},
        ),
        "start_derived_run": (
            "POST",
            "/api/v2/projects/project-1/runs:derive",
            {
                "project_id": "project-2",
                "source_run_id": "run-1",
                "policy": "retry_failed",
                "node_ids": ["node-1"],
                "client_request_id": "request-1",
            },
        ),
        "publish_project_input": (
            "POST",
            "/api/v2/projects/project-1/inputs",
            {
                "project_id": "project-2",
                "filename": "input.pdb",
                "content_base64": "",
            },
        ),
    }

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        for operation_id, (method, route, body) in cases.items():
            response = client.request(method, route, json=body)
            payload = response.json()
            assert response.status_code == 400, operation_id
            assert payload["error"]["code"] == "malformed_request", operation_id
            assert payload["error"]["details"]["field_path"] == [
                "project_id"
            ], operation_id


def test_backend_distinguishes_absent_empty_and_null_cancel_bodies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        absent = client.post(
            "/api/v2/projects/project-1/runs/run-1:cancel"
        )
        empty = client.post(
            "/api/v2/projects/project-1/runs/run-1:cancel",
            json={},
        )
        explicit_null = client.request(
            "POST",
            "/api/v2/projects/project-1/runs/run-1:cancel",
            content=b"null",
            headers={"content-type": "application/json"},
        )

    for response in (absent, empty):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "run_not_found"
    assert explicit_null.status_code == 400
    assert explicit_null.json()["error"]["code"] == "malformed_request"


def test_backend_rejects_invalid_project_identity_at_public_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        response = client.get(
            "/api/v2/projects/project:1/workflow/draft"
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["error"]["code"] == "malformed_request"
    assert payload["error"]["details"]["field_path"] == ["project_id"]


def test_backend_classifies_nested_workflow_version_before_authoring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    workflow = {
        "schema_version": "2.0.0",
        "workflow_id": "project-1",
        "nodes": [],
        "edges": [],
        "observation_selectors": [],
        "selection_objectives": [],
        "contract_lock": [],
    }

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        response = client.post(
            "/api/v2/projects/project-1/workflow:commit",
            json={
                "workflow": workflow,
            },
        )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "unsupported_schema_version"
    assert error["details"] == {
        "artifact_kind": "workflow",
        "expected_schema_version": "2.1.0",
        "received_schema_version": "2.0.0",
    }


def test_project_input_publication_rejects_invalid_project_id_at_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        response = client.post(
            "/api/v2/projects/bad!/inputs",
            json={"filename": "input.txt", "content_base64": "aW5wdXQ="},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_request"
    assert response.json()["error"]["details"] == {
        "field_path": ["project_id"]
    }


def test_backend_event_stream_rejects_undeclared_query_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        with client.websocket_connect(
            "/api/v2/projects/project-1/runs/run-1/events?legacy_cursor=1"
        ) as websocket:
            payload = websocket.receive_json()

    assert payload["error"]["code"] == "malformed_request"
    assert payload["error"]["details"]["field_path"] == ["legacy_cursor"]


def test_acceptance_request_is_derived_from_the_bundle_operation() -> None:
    request = {
        "project_id": "project-1",
        "workflow_commit_id": _WORKFLOW_COMMIT_ID,
        "client_request_id": "request-7",
    }

    assert prepare_rest_request("start_run", request) == PreparedRestRequest(
        method="POST",
        route="/api/v2/projects/project-1/runs",
        json_body={
            "workflow_commit_id": _WORKFLOW_COMMIT_ID,
            "client_request_id": "request-7",
        },
    )
    assert "/api/projects/" not in prepare_rest_request(
        "start_run",
        request,
    ).route


def test_inbound_rest_request_is_derived_from_the_bundle_operation() -> None:
    body = {
        "workflow_commit_id": _WORKFLOW_COMMIT_ID,
        "client_request_id": "request-7",
    }

    assert decode_rest_request(
        "start_run",
        path_parameters={"project_id": "project-1"},
        json_body=body,
    ) == {"project_id": "project-1", **body}
    with pytest.raises(
        ProtocolValidationError,
        match="multiple request sources",
    ) as collision:
        decode_rest_request(
            "start_run",
            path_parameters={"project_id": "project-1"},
            json_body={**body, "project_id": "project-2"},
        )
    assert collision.value.path == "$.project_id"


def test_event_stream_request_is_derived_from_the_bundle_contract() -> None:
    assert prepare_run_event_stream_request(
        {"project_id": "project-1", "run_id": "run-7"}
    ) == PreparedEventStreamRequest(
        transport="websocket",
        route="/api/v2/projects/project-1/runs/run-7/events",
        message_schema="#/$defs/RunEventStreamMessage",
    )
    assert prepare_run_event_stream_request(
        {
            "project_id": "project-1",
            "run_id": "run-7",
            "after_sequence": "cursor/1",
        }
    ).route == (
        "/api/v2/projects/project-1/runs/run-7/events"
        "?after_sequence=cursor%2F1"
    )
    with pytest.raises(ProtocolValidationError, match="project_id"):
        prepare_run_event_stream_request({"run_id": "run-7"})


def test_public_deep_commit_creates_draft_active_commit_and_runnable_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    with TestClient(
        create_application(frozen_catalog_override=builtin_frozen_catalog())
    ) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "deep commit"},
        ).json()["id"]
        workflow = {
            "schema_version": "2.1.0",
            "workflow_id": project_id,
            "nodes": [],
            "edges": [],
            "observation_selectors": [],
            "selection_objectives": [],
            "contract_lock": [],
        }
        committed_response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow,
            },
        )
        draft_response = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        )
        active_response = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )
        committed = committed_response.json()
        started_response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.get("workflow_commit_id"),
                "client_request_id": "deep-commit-run",
            },
        )

    assert committed_response.status_code == 200
    validate_response("commit_project_workflow", 200, committed)
    assert draft_response.status_code == 200
    validate_response(
        "project_workflow_draft",
        200,
        draft_response.json(),
    )
    assert draft_response.json()["draft_revision"] == 1
    assert active_response.json() == committed
    validate_response(
        "project_active_workflow_commit",
        200,
        active_response.json(),
    )
    assert started_response.status_code == 202
    started = started_response.json()
    validate_response("start_run", 202, started)
    assert started["workflow_commit_id"] == committed["workflow_commit_id"]
    assert started["workflow_commit_revision"] == 1
    with pytest.raises(ProtocolValidationError, match="project_id"):
        prepare_run_event_stream_request(
            {"project_id": "project/1", "run_id": "run-7"}
        )


def test_inbound_event_stream_request_is_derived_from_bundle_contract() -> None:
    assert decode_run_event_stream_request(
        path_parameters={"project_id": "project-1", "run_id": "run-7"},
        query_parameters={"after_sequence": "cursor-1"},
    ) == {
        "project_id": "project-1",
        "run_id": "run-7",
        "after_sequence": "cursor-1",
    }
    with pytest.raises(ProtocolValidationError, match="route-owned"):
        decode_run_event_stream_request(
            path_parameters={"project_id": "project-1", "run_id": "run-7"},
            query_parameters={"project_id": "project-2"},
        )


def test_acceptance_client_validates_response_without_backend_imports() -> None:
    receipt = {
        "project_id": "project-1",
        "run_id": "run-7",
        "workflow_commit_id": _WORKFLOW_COMMIT_ID,
        "workflow_commit_revision": 7,
        "admitted_sequence": 1,
        "event_cursor": "cursor-1",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v2/projects/project-1/runs"
        return httpx.Response(202, json=receipt)

    with PublicProtocolAcceptanceClient(
        "http://backend.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.request(
            "start_run",
            {
                "project_id": "project-1",
                "workflow_commit_id": _WORKFLOW_COMMIT_ID,
                "client_request_id": "request-7",
            },
        ) == receipt


def test_acceptance_client_prepares_project_and_input_publication() -> None:
    project = {
        "schema_namespace": PUBLIC_PROTOCOL_NAMESPACE,
        "id": "project-1",
        "name": "public project",
        "created_at": "2026-08-03T00:00:00+00:00",
        "modified_at": "2026-08-03T00:00:00+00:00",
        "seed": False,
    }
    publication = {
        "schema_namespace": PUBLIC_PROTOCOL_NAMESPACE,
        "project_id": "project-1",
        "filename": "source.pdb",
        "project_input_ref": "input-1",
        "size": 5,
        "content_digest": (
            "sha256:" + hashlib.sha256(b"ATOM\n").hexdigest()
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/projects":
            assert request.method == "POST"
            assert json.loads(request.content) == {"name": "public project"}
            return httpx.Response(201, json=project)
        if request.url.path == "/api/v2/projects/project-1/inputs":
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "filename": "source.pdb",
                "content_base64": "QVRPTQo=",
            }
            return httpx.Response(201, json=publication)
        assert request.url.path == "/api/v2/projects/project-1/inputs/input-1"
        assert request.method == "GET"
        assert request.content == b""
        return httpx.Response(200, json=publication)

    with PublicProtocolAcceptanceClient(
        "http://backend.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.create_project("public project") == project
        assert client.publish_project_input(
            "project-1",
            filename="source.pdb",
            content=b"ATOM\n",
        ) == publication
        assert client.project_input_metadata(
            "project-1",
            "input-1",
        ) == publication
