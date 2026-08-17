"""FastAPI server exposing the sole supported v2 public runtime."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import math
import os
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, AsyncGenerator

from contextlib import ExitStack, asynccontextmanager, suppress
from importlib.resources import as_file, files
from fastapi import (
    FastAPI,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError

from core.module_package import build_discovered_frozen_catalog
from core.port_types import FrozenCatalog
from core.project import (
    PROJECT_SCHEMA_VERSION,
    ProjectManager,
    ProtectedProjectError,
)
from core.run_execution_v2 import (
    EnvironmentConfiguration,
    ResultReplaySource,
    LedgerTransactionStore,
    V2RunError,
    V2RunService,
    run_timestamp,
)
from core.storage import StoragePathError
from core.workflow_authoring_v2 import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow_v2 import (
    WorkflowDocumentError,
    parse_workflow_document,
    workflow_document_from_admitted_public,
)
from protein_workbench_public import (
    ProtocolValidationError,
    REST_BODY_ABSENT,
    artifact_content_disposition,
    bundle_bytes,
    bundle_digest,
    decode_rest_request,
    decode_run_event_stream_request,
    load_bundle,
    validate_artifact_response,
    validate_typed_value_response,
    validate_error,
    validate_event,
    validate_response,
)


_LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    module_packages_package: str = "modules",
    frozen_catalog_override: FrozenCatalog | None = None,
    v2_environment_configuration: (
        Mapping[tuple[str, str], Mapping[str, Any]] | None
    ) = None,
    v2_result_replay_source: ResultReplaySource | None = None,
    _v2_ledger_transaction_store: LedgerTransactionStore | None = None,
    _v2_wait_for_workers_on_shutdown: bool = True,
    _install_canonical_seed: bool | None = None,
) -> FastAPI:
    """Create one backend from one startup-frozen v2 Catalog."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        catalog_candidate = (
            frozen_catalog_override
            if frozen_catalog_override is not None
            else build_discovered_frozen_catalog(module_packages_package)
        )
        project_manager = ProjectManager(
            root_dir=os.environ.get("PROTEIN_WORKBENCH_PROJECT_ROOT", "projects"),
            cache_root=os.environ.get("PROTEIN_WORKBENCH_CACHE_ROOT"),
            output_root=os.environ.get("PROTEIN_WORKBENCH_OUTPUT_ROOT"),
            run_root=os.environ.get("PROTEIN_WORKBENCH_RUN_ROOT"),
        )
        app.state.project_manager = project_manager
        app.state.frozen_catalog = catalog_candidate
        app.state.workflow_authoring_v2 = WorkflowAuthoringService(
            project_manager,
            catalog_candidate,
        )
        install_canonical_seed = (
            frozen_catalog_override is None
            if _install_canonical_seed is None
            else _install_canonical_seed
        ) and module_packages_package == "modules"
        with ExitStack() as asset_stack:
            canonical_structure = asset_stack.enter_context(
                as_file(files("pdbs").joinpath("3GB1.pdb"))
            )
            canonical_v2_workflow = asset_stack.enter_context(
                as_file(
                    files("examples").joinpath(
                        "v2",
                        "canonical-3gb1.workflow.json",
                    )
                )
            )
            canonical_seed_workflow = parse_workflow_document(
                json.loads(canonical_v2_workflow.read_text(encoding="utf-8"))
            )
            if install_canonical_seed:
                app.state.workflow_authoring_v2.install_seed_commit(
                    locked_workflow=canonical_seed_workflow,
                    input_sources={"3GB1.pdb": canonical_structure},
                )
        app.state.run_execution_v2 = V2RunService(
            project_manager,
            catalog_candidate,
            app.state.workflow_authoring_v2,
            EnvironmentConfiguration(v2_environment_configuration),
            v2_result_replay_source,
            _v2_ledger_transaction_store,
        )
        yield
        if _v2_wait_for_workers_on_shutdown:
            await asyncio.to_thread(app.state.run_execution_v2.shutdown)

    app = FastAPI(title="Protein Workbench", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(StoragePathError)
    async def storage_path_error_handler(
        request: Request,
        error: StoragePathError,
    ) -> JSONResponse:
        if request.url.path.startswith("/api/v2/"):
            incident_id = report_public_internal_error(
                error,
                transport="REST",
            )
            return public_error_response(
                "internal_error",
                "Internal server error",
                {"incident_id": incident_id},
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "kind": "invalid_storage_path",
                    "field": error.field,
                    "message": str(error),
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        body_error = any(
            item.get("loc", (None,))[0] == "body"
            for item in error.errors()
        )
        if request.url.path.startswith("/api/v2/"):
            return public_error_response(
                "malformed_request",
                (
                    "Request body is invalid"
                    if body_error
                    else "Request is invalid"
                ),
                {"field_path": []},
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "kind": (
                        "invalid_request_body"
                        if body_error
                        else "invalid_request"
                    ),
                    "message": (
                        "Request body is invalid"
                        if body_error
                        else "Request is invalid"
                    ),
                }
            },
        )

    public_bundle = load_bundle()
    protocol_discovery = public_bundle["bundle_discovery"]
    rest_operations = public_bundle["rest_operations"]
    run_event_stream = public_bundle["run_event_stream"]

    @app.get(
        protocol_discovery["route"],
        include_in_schema=False,
    )
    async def public_protocol_bundle(request: Request) -> Response:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            if query_parameters:
                field = sorted(query_parameters)[0]
                raise ProtocolValidationError(
                    f"$.{field}",
                    "query parameter is not declared by protocol discovery",
                )
            if json_body is not REST_BODY_ABSENT:
                raise ProtocolValidationError(
                    "$",
                    "protocol discovery does not declare a body",
                )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        return Response(
            content=bundle_bytes(),
            media_type=protocol_discovery["media_type"],
            headers={
                protocol_discovery["digest_header"]: bundle_digest(),
            },
        )

    catalog_operation = rest_operations["catalog_snapshot"]

    @app.get(catalog_operation["route"], include_in_schema=False)
    async def public_catalog_snapshot(request: Request) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            decode_rest_request(
                "catalog_snapshot",
                query_parameters=query_parameters,
                json_body=json_body,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        payload = request.app.state.frozen_catalog.public_snapshot(
            protocol_digest=bundle_digest(),
        )
        validate_response(
            "catalog_snapshot",
            catalog_operation["response"]["success_status"],
            payload,
        )
        return payload

    def public_error_payload(
        code: str,
        message: str,
        details: Mapping[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        definition = load_bundle()["structured_errors"]["vocabulary"][code]
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "error": {
                "code": code,
                "message": message,
                "retryable": definition["retryable"],
                "correlation_id": f"error-{uuid.uuid4().hex}",
                "details": dict(details),
            },
        }
        status = definition["http_status"]
        validate_error(payload, status=status)
        return status, payload

    def public_error_response(
        code: str,
        message: str,
        details: Mapping[str, Any],
    ) -> JSONResponse:
        status, payload = public_error_payload(code, message, details)
        return JSONResponse(status_code=status, content=payload)

    def report_public_internal_error(
        error: Exception,
        *,
        transport: str,
    ) -> str:
        incident_id = f"incident-{uuid.uuid4().hex}"
        _LOGGER.error(
            "Unhandled public v2 %s error incident_id=%s exception_type=%s",
            transport,
            incident_id,
            type(error).__name__,
            exc_info=True,
        )
        return incident_id

    @app.middleware("http")
    async def public_v2_internal_error_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as error:
            if not request.url.path.startswith("/api/v2/"):
                raise
            incident_id = report_public_internal_error(
                error,
                transport="REST",
            )
            return public_error_response(
                "internal_error",
                "Internal server error",
                {"incident_id": incident_id},
            )

    def protocol_error_field_path(
        error: ProtocolValidationError,
    ) -> list[str | int]:
        field_path: list[str | int] = []
        for match in re.finditer(r"\.([^.[\]]+)|\[([0-9]+)\]", error.path):
            name, index = match.groups()
            field_path.append(name if name is not None else int(index))
        return field_path

    def protocol_error_response(
        error: ProtocolValidationError,
        json_body: Any = None,
    ) -> JSONResponse:
        if error.path == "$.workflow.schema_version":
            workflow_payload = (
                json_body.get("workflow")
                if isinstance(json_body, Mapping)
                else None
            )
            received = (
                workflow_payload.get("schema_version", "missing")
                if isinstance(workflow_payload, Mapping)
                else "invalid"
            )
            return public_error_response(
                "unsupported_schema_version",
                "Workflow schema version is unsupported",
                {
                    "artifact_kind": "workflow",
                    "expected_schema_version": "2.1.0",
                    "received_schema_version": (
                        str(received)[:64] or "missing"
                    ),
                },
            )
        return public_error_response(
            "malformed_request",
            str(error),
            {"field_path": protocol_error_field_path(error)},
        )

    def reject_duplicate_request_keys(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key {key!r}")
            result[key] = value
        return result

    def parse_finite_request_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-I-JSON numeric value {value!r}")
        return parsed

    async def public_rest_wire_sources(
        request: Request,
    ) -> tuple[dict[str, str], Any]:
        query_parameters: dict[str, str] = {}
        for name, value in request.query_params.multi_items():
            if name in query_parameters:
                raise ProtocolValidationError(
                    f"$.{name}",
                    "query parameter must appear exactly once",
                )
            query_parameters[name] = value

        raw_body = await request.body()
        if raw_body == b"":
            return query_parameters, REST_BODY_ABSENT
        try:
            json_body = json.loads(
                raw_body.decode("utf-8"),
                object_pairs_hook=reject_duplicate_request_keys,
                parse_float=parse_finite_request_float,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-I-JSON numeric value {value!r}")
                ),
            )
        except (UnicodeError, ValueError) as error:
            raise ProtocolValidationError(
                "$",
                "request body must be valid I-JSON",
            ) from error
        return query_parameters, json_body

    def workflow_document_error_response(
        error: WorkflowDocumentError,
        payload: Any,
    ) -> JSONResponse:
        if error.code == "unsupported_schema_version":
            received = (
                payload.get("schema_version", "missing")
                if isinstance(payload, Mapping)
                else "invalid"
            )
            details: Mapping[str, Any] = {
                "artifact_kind": "workflow",
                "expected_schema_version": "2.1.0",
                "received_schema_version": str(received)[:64] or "missing",
            }
        elif error.code == "contract_digest_mismatch":
            details = {
                "issues": [
                    {
                        "code": error.code,
                        "severity": "error",
                        "message": str(error),
                        "field_path": ["contract_lock"],
                    }
                ]
            }
        else:
            details = {"field_path": ["workflow"]}
        return public_error_response(error.code, str(error), details)

    def authoring_error_response(
        error: WorkflowAuthoringError,
    ) -> JSONResponse:
        return public_error_response(
            error.code,
            str(error),
            error.details,
        )

    @app.get(
        rest_operations["project_workflow_draft"]["route"],
        include_in_schema=False,
    )
    async def public_project_workflow_draft(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "project_workflow_draft",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            payload = (
                request.app.state.workflow_authoring_v2.load_draft(
                    admitted["project_id"]
                ).to_public()
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("project_workflow_draft", 200, payload)
        return payload

    @app.put(
        rest_operations["save_project_workflow_draft"]["route"],
        include_in_schema=False,
    )
    async def public_save_project_workflow_draft(
        request: Request,
        project_id: str,
    ) -> Any:
        workflow_payload: Any = None
        json_body: Any = REST_BODY_ABSENT
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "save_project_workflow_draft",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            workflow_payload = admitted["workflow"]
            workflow = workflow_document_from_admitted_public(
                workflow_payload
            )
            snapshot = (
                request.app.state.workflow_authoring_v2.save_draft(
                    admitted["project_id"],
                    workflow=workflow,
                ).to_public()
            )
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except ProtocolValidationError as error:
            return protocol_error_response(error, json_body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("save_project_workflow_draft", 200, snapshot)
        return snapshot

    @app.get(
        rest_operations["project_active_workflow_commit"]["route"],
        include_in_schema=False,
    )
    async def public_project_active_workflow_commit(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "project_active_workflow_commit",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            receipt = (
                request.app.state.workflow_authoring_v2.load_active_commit(
                    admitted["project_id"]
                ).to_public()
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("project_active_workflow_commit", 200, receipt)
        return receipt

    @app.post(
        rest_operations["commit_project_workflow"]["route"],
        include_in_schema=False,
    )
    async def public_commit_project_workflow(
        request: Request,
        project_id: str,
    ) -> Any:
        workflow_payload: Any = None
        json_body: Any = REST_BODY_ABSENT
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "commit_project_workflow",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            workflow_payload = admitted["workflow"]
            workflow = workflow_document_from_admitted_public(
                workflow_payload
            )
            receipt = request.app.state.workflow_authoring_v2.commit(
                admitted["project_id"],
                workflow=workflow,
            ).to_public()
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except ProtocolValidationError as error:
            return protocol_error_response(error, json_body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("commit_project_workflow", 200, receipt)
        return receipt

    @app.post(
        rest_operations["start_run"]["route"],
        include_in_schema=False,
    )
    async def public_start_run(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "start_run",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            receipt = request.app.state.run_execution_v2.start_background(
                admitted["project_id"],
                workflow_commit_id=admitted["workflow_commit_id"],
                client_request_id=admitted["client_request_id"],
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        validate_response("start_run", 202, receipt)
        return JSONResponse(status_code=202, content=receipt)

    @app.post(
        rest_operations["cancel_run"]["route"],
        include_in_schema=False,
    )
    async def public_cancel_run(
        request: Request,
        project_id: str,
        run_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "cancel_run",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            receipt = await asyncio.to_thread(
                request.app.state.run_execution_v2.cancel,
                admitted["project_id"],
                admitted["run_id"],
                after_cursor=admitted.get("after_sequence"),
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        validate_response("cancel_run", 200, receipt)
        return receipt

    @app.post(
        rest_operations["start_derived_run"]["route"],
        include_in_schema=False,
    )
    async def public_start_derived_run(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "start_derived_run",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            receipt = (
                request.app.state.run_execution_v2.start_derived_background(
                    admitted["project_id"],
                    source_run_id=admitted["source_run_id"],
                    policy=admitted["policy"],
                    node_ids=admitted["node_ids"],
                    client_request_id=admitted["client_request_id"],
                )
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        validate_response("start_derived_run", 202, receipt)
        return JSONResponse(status_code=202, content=receipt)

    @app.get(
        rest_operations["run_projection"]["route"],
        include_in_schema=False,
    )
    async def public_run_projection(
        request: Request,
        project_id: str,
        run_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "run_projection",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            projection = request.app.state.run_execution_v2.projection(
                admitted["project_id"],
                admitted["run_id"],
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        validate_response("run_projection", 200, projection)
        return projection

    @app.get(
        rest_operations["typed_value_retrieval"]["route"],
        include_in_schema=False,
    )
    async def public_v2_typed_value(
        request: Request,
        project_id: str,
        run_id: str,
        node_id: str,
        output_port: str,
        value_index: int,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "typed_value_retrieval",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                    "node_id": node_id,
                    "output_port": output_port,
                    "value_index": value_index,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            metadata, body = request.app.state.run_execution_v2.typed_value(
                admitted["project_id"],
                admitted["run_id"],
                admitted["node_id"],
                admitted["output_port"],
                admitted["value_index"],
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        typed_value = metadata["typed_value"]
        headers = {
            "Content-Length": str(typed_value["size"]),
            "Content-Type": "application/json",
            "Digest": typed_value["value_content_digest"],
            "ETag": f'"{typed_value["value_content_digest"]}"',
            "X-Port-Content-Digest": typed_value[
                "port_content_digest"
            ],
            "X-Port-Type-Kind": typed_value["port_type"][
                "contract_kind"
            ],
            "X-Port-Type-Id": typed_value["port_type"]["contract_id"],
            "X-Port-Type-Version": typed_value["port_type"][
                "contract_version"
            ],
            "X-Port-Type-Digest": typed_value["port_type"][
                "contract_digest"
            ],
            "X-Value-Count": str(typed_value["value_count"]),
            "X-Value-Index": str(typed_value["value_index"]),
            "X-Value-Manifest-Reference": typed_value[
                "value_manifest_reference"
            ],
        }
        validate_typed_value_response(metadata, headers, body)
        return Response(content=body, media_type=None, headers=headers)

    @app.get(
        rest_operations["artifact_retrieval"]["route"],
        include_in_schema=False,
    )
    async def public_v2_artifact(
        request: Request,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "artifact_retrieval",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                    "artifact_reference": artifact_reference,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            artifact, body = request.app.state.run_execution_v2.artifact(
                admitted["project_id"],
                admitted["run_id"],
                admitted["artifact_reference"],
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        content_disposition = artifact_content_disposition(
            artifact["filename"]
        )
        headers = {
            "Content-Disposition": content_disposition,
            "Content-Length": str(artifact["size"]),
            "Content-Type": artifact["media_type"],
            "Digest": artifact["content_digest"],
        }
        validate_artifact_response(
            {
                "artifact": artifact,
                "content_disposition": content_disposition,
            },
            headers,
            body,
        )
        return Response(
            content=body,
            media_type=None,
            headers=headers,
        )

    @app.websocket(
        run_event_stream["route"].partition("?")[0]
    )
    async def public_v2_run_events(
        websocket: WebSocket,
        project_id: str,
        run_id: str,
    ) -> None:
        await websocket.accept()
        after_sequence: str | None = None
        try:
            query_parameters: dict[str, str] = {}
            for name, value in websocket.query_params.multi_items():
                if name in query_parameters:
                    raise ProtocolValidationError(
                        f"$.{name}",
                        "query parameter must appear exactly once",
                    )
                query_parameters[name] = value
            after_sequence = query_parameters.get("after_sequence")
            admitted = decode_run_event_stream_request(
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                },
                query_parameters=query_parameters,
            )
            project_id = admitted["project_id"]
            run_id = admitted["run_id"]
            after_sequence = admitted.get("after_sequence")
            (
                replay_after_sequence,
                replay_after_cursor,
                replay_through_sequence,
                replay_through_cursor,
                events,
                terminal,
            ) = websocket.app.state.run_execution_v2.replay_window(
                project_id,
                run_id,
                after_sequence,
            )
            replay_started = {
                "schema_namespace": "protein-workbench-public/v2",
                "project_id": project_id,
                "run_id": run_id,
                "sequence": replay_after_sequence,
                "cursor": replay_after_cursor,
                "emitted_at": run_timestamp(),
                "event": {
                    "type": "replay_started",
                    "replay_through_cursor": replay_through_cursor,
                    **(
                        {"after_sequence": after_sequence}
                        if after_sequence is not None
                        else {}
                    ),
                },
            }
            validate_event(replay_started)
            await websocket.send_json(replay_started)
            for event in events:
                validate_event(event)
                await websocket.send_json(event)
            replay_complete = {
                "schema_namespace": "protein-workbench-public/v2",
                "project_id": project_id,
                "run_id": run_id,
                "sequence": replay_through_sequence,
                "cursor": replay_through_cursor,
                "emitted_at": run_timestamp(),
                "event": {
                    "type": "replay_complete",
                    "live_from_cursor": replay_through_cursor,
                },
            }
            validate_event(replay_complete)
            await websocket.send_json(replay_complete)
            live_after_sequence = replay_through_sequence
            while not terminal:
                live_events, observed_sequence, terminal = await asyncio.to_thread(
                    websocket.app.state.run_execution_v2.wait_for_public_events,
                    project_id,
                    run_id,
                    live_after_sequence,
                    timeout_seconds=1.0,
                )
                for event in live_events:
                    validate_event(event)
                    await websocket.send_json(event)
                live_after_sequence = observed_sequence
            await websocket.close(code=1000)
        except (ProtocolValidationError, V2RunError) as error:
            if isinstance(error, V2RunError):
                code = error.code
                message = str(error)
                details = error.details
            else:
                if (
                    error.path == "$.after_sequence"
                    and after_sequence is not None
                ):
                    code = "invalid_cursor"
                    message = "Run Event Stream cursor is invalid"
                    details = {
                        "after_sequence": (
                            after_sequence
                            if isinstance(after_sequence, str)
                            and 1 <= len(after_sequence) <= 512
                            else "invalid"
                        )
                    }
                else:
                    code = "malformed_request"
                    message = str(error)
                    details = {
                        "field_path": protocol_error_field_path(error)
                    }
            _, payload = public_error_payload(code, message, details)
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json(payload)
            await websocket.close(code=1008)
        except Exception as error:
            incident_id = report_public_internal_error(
                error,
                transport="WebSocket",
            )
            _, payload = public_error_payload(
                "internal_error",
                "Internal server error",
                {"incident_id": incident_id},
            )
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json(payload)
            await websocket.close(code=1011)

    create_project_operation = rest_operations["create_project"]

    @app.post(create_project_operation["route"], include_in_schema=False)
    async def public_create_project(request: Request) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "create_project",
                query_parameters=query_parameters,
                json_body=json_body,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        meta = request.app.state.project_manager.create(admitted["name"])
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "id": meta.id,
            "name": meta.name,
            "created_at": meta.created_at,
            "modified_at": meta.modified_at,
            "seed": meta.seed,
        }
        status = create_project_operation["response"]["success_status"]
        validate_response("create_project", status, payload)
        return JSONResponse(status_code=status, content=payload)

    publish_input_operation = rest_operations["publish_project_input"]

    @app.post(publish_input_operation["route"], include_in_schema=False)
    async def public_publish_project_input(
        request: Request,
        project_id: str,
    ) -> Any:
        manager = request.app.state.project_manager
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "publish_project_input",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            content = base64.b64decode(admitted["content_base64"])
            project = manager.load_meta(admitted["project_id"])
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except ValueError:
            return public_error_response(
                "unsupported_schema_version",
                "Project metadata is not a supported exact v2 artifact",
                {
                    "artifact_kind": "project",
                    "expected_schema_version": PROJECT_SCHEMA_VERSION,
                    "received_schema_version": "unknown",
                },
            )
        if project is None:
            return public_error_response(
                "project_not_found",
                "Project was not found",
                {
                    "resource_kind": "project",
                    "resource_id": admitted["project_id"],
                },
            )
        try:
            published = manager.publish_input(
                admitted["project_id"],
                f"input-{uuid.uuid4().hex}",
                content,
                filename=admitted["filename"],
            )
        except ProtectedProjectError:
            return public_error_response(
                "cross_scope_access_denied",
                "Protected Project cannot be changed through this scope",
                {"requested_project_id": admitted["project_id"]},
            )
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "project_id": admitted["project_id"],
            **published,
        }
        status = publish_input_operation["response"]["success_status"]
        validate_response("publish_project_input", status, payload)
        return JSONResponse(status_code=status, content=payload)

    input_metadata_operation = rest_operations["project_input_metadata"]

    @app.get(input_metadata_operation["route"], include_in_schema=False)
    async def public_project_input_metadata(
        request: Request,
        project_id: str,
        project_input_ref: str,
    ) -> Any:
        manager = request.app.state.project_manager
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "project_input_metadata",
                path_parameters={
                    "project_id": project_id,
                    "project_input_ref": project_input_ref,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            project = manager.load_meta(admitted["project_id"])
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except ValueError:
            return public_error_response(
                "unsupported_schema_version",
                "Project metadata is not a supported exact v2 artifact",
                {
                    "artifact_kind": "project",
                    "expected_schema_version": PROJECT_SCHEMA_VERSION,
                    "received_schema_version": "unknown",
                },
            )
        if project is None:
            return public_error_response(
                "project_not_found",
                "Project was not found",
                {
                    "resource_kind": "project",
                    "resource_id": admitted["project_id"],
                },
            )
        try:
            descriptor, _ = manager.read_input(
                admitted["project_id"],
                admitted["project_input_ref"],
            )
        except FileNotFoundError:
            return public_error_response(
                "project_input_not_found",
                "Project Input was not found",
                {
                    "resource_kind": "project_input",
                    "resource_id": admitted["project_input_ref"],
                },
            )
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "project_id": admitted["project_id"],
            **descriptor,
        }
        status = input_metadata_operation["response"]["success_status"]
        validate_response("project_input_metadata", status, payload)
        return JSONResponse(status_code=status, content=payload)

    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    """Launch the installed v2 backend without source-checkout assumptions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parsed = parser.parse_args(argv)
    import uvicorn

    uvicorn.run(
        app,
        host=parsed.host,
        port=parsed.port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
