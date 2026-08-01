"""Public, implementation-independent contract tests for protocol v2."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
import httpx

from core.server import create_app
from protein_workbench_public import (
    PUBLIC_PROTOCOL_NAMESPACE,
    PreparedEventStreamRequest,
    PreparedRestRequest,
    ProtocolValidationError,
    bundle_bytes,
    bundle_digest,
    load_bundle,
    prepare_run_event_stream_request,
    prepare_rest_request,
    validate_artifact_response,
    validate_error,
    validate_event,
    validate_request,
    validate_response,
    validate_schema,
)
from tests.public_protocol_acceptance_client import (
    PublicProtocolAcceptanceClient,
)


def test_public_protocol_bundle_has_stable_canonical_identity() -> None:
    bundle = load_bundle()
    canonical = bundle_bytes()
    digest = bundle_digest()

    assert bundle["schema_namespace"] == "protein-workbench-public/v2"
    assert PUBLIC_PROTOCOL_NAMESPACE == bundle["schema_namespace"]
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


def test_bundle_closes_every_supported_rest_operation() -> None:
    bundle = load_bundle()
    operations = bundle["rest_operations"]

    assert set(operations) == {
        "artifact_retrieval",
        "cancel_run",
        "catalog_snapshot",
        "project_workflow_snapshot",
        "relock_project_workflow",
        "run_projection",
        "save_project_workflow",
        "start_derived_run",
        "start_run",
        "workflow_compile",
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
        "project_workflow_snapshot": (
            "GET",
            "/api/v2/projects/{project_id}/workflow",
        ),
        "relock_project_workflow": (
            "POST",
            "/api/v2/projects/{project_id}/workflow:relock",
        ),
        "run_projection": (
            "GET",
            "/api/v2/projects/{project_id}/runs/{run_id}",
        ),
        "save_project_workflow": (
            "PUT",
            "/api/v2/projects/{project_id}/workflow",
        ),
        "start_derived_run": (
            "POST",
            "/api/v2/projects/{project_id}/runs:derive",
        ),
        "start_run": ("POST", "/api/v2/projects/{project_id}/runs"),
        "workflow_compile": (
            "POST",
            "/api/v2/projects/{project_id}/workflow:compile",
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
    assert errors["vocabulary_version"] == "2.1.0"
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
        "cache_identity_conflict",
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
        "project_not_found",
        "protocol_mismatch",
        "readiness_rejected",
        "run_not_found",
        "selection_failed",
        "unsupported_schema_version",
        "workflow_not_found",
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
        "provider_chain_order": ["B", "A"],
        "entries": [
            {
                "residue_id": "A:6",
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "B:20",
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
    validate_request("catalog_snapshot", {})
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_request("catalog_snapshot", {"v1_fallback": True})

    request = {
        "project_id": "project-1",
        "workflow_revision": 7,
        "compile_id": "compile-7",
        "client_request_id": "request-7",
    }
    validate_request("start_run", request)
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_request("start_run", {**request, "seed": 42})

    receipt = {
        "project_id": "project-1",
        "run_id": "run-7",
        "workflow_revision": 7,
        "compile_id": "compile-7",
        "admitted_sequence": 1,
        "event_cursor": "cursor-1",
    }
    validate_response("start_run", 202, receipt)
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_response("start_run", 202, {**receipt, "status": "queued"})


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
            "size": len(body),
            "content_digest": content_digest,
        },
        "content_disposition": 'attachment; filename="structure.pdb"',
    }
    headers = {
        "Content-Disposition": metadata["content_disposition"],
        "Content-Length": str(len(body)),
        "Content-Type": "chemical/x-pdb",
        "Digest": content_digest,
    }

    validate_artifact_response(metadata, headers, body)
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

    with TestClient(create_app()) as client:
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


def test_acceptance_request_is_derived_from_the_bundle_operation() -> None:
    request = {
        "project_id": "project-1",
        "workflow_revision": 7,
        "compile_id": "compile-7",
        "client_request_id": "request-7",
    }

    assert prepare_rest_request("start_run", request) == PreparedRestRequest(
        method="POST",
        route="/api/v2/projects/project-1/runs",
        json_body={
            "workflow_revision": 7,
            "compile_id": "compile-7",
            "client_request_id": "request-7",
        },
    )
    assert "/api/projects/" not in prepare_rest_request(
        "start_run",
        request,
    ).route


def test_event_stream_request_is_derived_from_the_bundle_contract() -> None:
    assert prepare_run_event_stream_request(
        {"project_id": "project/1", "run_id": "run/7"}
    ) == PreparedEventStreamRequest(
        transport="websocket",
        route="/api/v2/projects/project%2F1/runs/run%2F7/events",
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


def test_acceptance_client_validates_response_without_backend_imports() -> None:
    receipt = {
        "project_id": "project-1",
        "run_id": "run-7",
        "workflow_revision": 7,
        "compile_id": "compile-7",
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
                "workflow_revision": 7,
                "compile_id": "compile-7",
                "client_request_id": "request-7",
            },
        ) == receipt
