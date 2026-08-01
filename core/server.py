"""FastAPI server exposing the sole supported v2 public runtime."""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, AsyncGenerator

from contextlib import ExitStack, asynccontextmanager, suppress
from importlib.resources import as_file, files
from fastapi import (
    Body,
    FastAPI,
    File,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from core.module_package import build_discovered_frozen_catalog
from core.port_types import FrozenCatalog
from core.project import (
    MAX_PROJECT_INPUT_BYTES,
    ProjectManager,
)
from core.run_execution_v2 import (
    EnvironmentConfiguration,
    ResultReplaySource,
    V2RunError,
    V2RunService,
    run_timestamp,
)
from core.storage import (
    StoragePathError,
    validate_identifier,
)
from core.workflow_authoring_v2 import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow_v2 import (
    WorkflowCompileError,
    WorkflowDocumentError,
    parse_workflow_document,
)
from protein_workbench_public import (
    ProtocolValidationError,
    bundle_bytes,
    bundle_digest,
    load_bundle,
    validate_artifact_response,
    validate_error,
    validate_event,
    validate_request,
    validate_response,
    validate_schema,
)

TRUSTED_BROWSER_ORIGINS = frozenset(
    {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    }
)


def _is_trusted_browser_origin(request: Request | WebSocket) -> bool:
    origin = request.headers.get("origin")
    return origin is None or origin in TRUSTED_BROWSER_ORIGINS


def create_app(
    *,
    module_packages_package: str = "modules",
    frozen_catalog_override: FrozenCatalog | None = None,
    v2_environment_configuration: (
        Mapping[tuple[str, str], Mapping[str, Any]] | None
    ) = None,
    v2_result_replay_source: ResultReplaySource | None = None,
    _v2_wait_for_workers_on_shutdown: bool = True,
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
            project_manager.ensure_seed_project_v2(
                canonical_v2_workflow,
                input_sources={"3GB1.pdb": canonical_structure},
            )
        app.state.project_manager = project_manager
        app.state.frozen_catalog = catalog_candidate
        app.state.workflow_authoring_v2 = WorkflowAuthoringService(
            project_manager,
            catalog_candidate,
        )
        app.state.run_execution_v2 = V2RunService(
            project_manager,
            catalog_candidate,
            app.state.workflow_authoring_v2,
            EnvironmentConfiguration(v2_environment_configuration),
            v2_result_replay_source,
        )
        yield
        if _v2_wait_for_workers_on_shutdown:
            await asyncio.to_thread(app.state.run_execution_v2.shutdown)

    app = FastAPI(title="Protein Workbench", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def enforce_trusted_mutation_origin(
        request: Request,
        call_next: Any,
    ) -> Any:
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and not _is_trusted_browser_origin(request)
        ):
            if request.url.path.startswith("/api/v2/projects/"):
                path_parts = request.url.path.split("/")
                requested_project_id = (
                    path_parts[4]
                    if len(path_parts) > 4
                    else "unknown-project"
                )
                try:
                    validate_identifier(
                        requested_project_id,
                        "project_id",
                    )
                except StoragePathError:
                    requested_project_id = "unknown-project"
                return public_error_response(
                    "cross_scope_access_denied",
                    "Browser origin is not allowed",
                    {"requested_project_id": requested_project_id},
                )
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "kind": "untrusted_origin",
                        "message": "Browser origin is not allowed",
                    }
                },
            )
        return await call_next(request)

    @app.exception_handler(StoragePathError)
    async def storage_path_error_handler(
        request: Request,
        error: StoragePathError,
    ) -> JSONResponse:
        del request
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(TRUSTED_BROWSER_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    protocol_discovery = load_bundle()["bundle_discovery"]

    @app.get(
        protocol_discovery["route"],
        include_in_schema=False,
    )
    async def public_protocol_bundle() -> Response:
        return Response(
            content=bundle_bytes(),
            media_type=protocol_discovery["media_type"],
            headers={
                protocol_discovery["digest_header"]: bundle_digest(),
            },
        )

    catalog_operation = load_bundle()["rest_operations"]["catalog_snapshot"]

    @app.get(catalog_operation["route"], include_in_schema=False)
    async def public_catalog_snapshot(request: Request) -> dict[str, Any]:
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
        "/api/v2/projects/{project_id}/workflow",
        include_in_schema=False,
    )
    async def public_project_workflow_snapshot(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            validate_request(
                "project_workflow_snapshot",
                {"project_id": project_id},
            )
            payload = request.app.state.workflow_authoring_v2.load(project_id)
        except ProtocolValidationError as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": ["project_id"]},
            )
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("project_workflow_snapshot", 200, payload)
        return payload

    @app.put(
        "/api/v2/projects/{project_id}/workflow",
        include_in_schema=False,
    )
    async def public_save_project_workflow(
        request: Request,
        project_id: str,
        payload: Any = Body(...),
    ) -> Any:
        workflow_payload = (
            payload.get("workflow")
            if isinstance(payload, Mapping)
            else payload
        )
        try:
            workflow = parse_workflow_document(workflow_payload)
            combined = {"project_id": project_id, **payload}
            validate_request("save_project_workflow", combined)
            snapshot = request.app.state.workflow_authoring_v2.save(
                project_id,
                expected_workflow_revision=payload[
                    "expected_workflow_revision"
                ],
                workflow=workflow,
            )
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except ProtocolValidationError as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("save_project_workflow", 200, snapshot)
        return snapshot

    @app.post(
        "/api/v2/projects/{project_id}/workflow:relock",
        include_in_schema=False,
    )
    async def public_relock_project_workflow(
        request: Request,
        project_id: str,
        payload: Any = Body(...),
    ) -> Any:
        try:
            combined = {"project_id": project_id, **payload}
            validate_request("relock_project_workflow", combined)
            snapshot = request.app.state.workflow_authoring_v2.relock(
                project_id,
                workflow_revision=payload["workflow_revision"],
            )
        except (ProtocolValidationError, TypeError) as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        except WorkflowCompileError as error:
            code = (
                error.code
                if error.code in {
                    "contract_digest_mismatch",
                    "inactive_generation",
                }
                else "compile_rejected"
            )
            return public_error_response(
                code,
                str(error),
                {"issues": [error.issue()]},
            )
        validate_response("relock_project_workflow", 200, snapshot)
        return snapshot

    @app.post(
        "/api/v2/projects/{project_id}/workflow:compile",
        include_in_schema=False,
    )
    async def public_compile_workflow(
        request: Request,
        project_id: str,
        payload: Any = Body(...),
    ) -> Any:
        workflow_payload = (
            payload.get("workflow")
            if isinstance(payload, Mapping)
            else payload
        )
        try:
            workflow = parse_workflow_document(workflow_payload)
            combined = {"project_id": project_id, **payload}
            validate_request("workflow_compile", combined)
            compiled = request.app.state.workflow_authoring_v2.compile(
                project_id,
                workflow_revision=payload["workflow_revision"],
                workflow=workflow,
            )
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except ProtocolValidationError as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        except WorkflowCompileError as error:
            code = (
                error.code
                if error.code in {
                    "contract_digest_mismatch",
                    "inactive_generation",
                }
                else "compile_rejected"
            )
            return public_error_response(
                code,
                str(error),
                {"issues": [error.issue()]},
            )
        receipt = compiled.public_receipt()
        validate_response("workflow_compile", 200, receipt)
        return receipt

    @app.post(
        "/api/v2/projects/{project_id}/runs",
        include_in_schema=False,
    )
    async def public_start_run(
        request: Request,
        project_id: str,
        payload: Any = Body(...),
    ) -> Any:
        try:
            combined = {"project_id": project_id, **payload}
            validate_request("start_run", combined)
            receipt = request.app.state.run_execution_v2.start_background(
                project_id,
                workflow_revision=payload["workflow_revision"],
                compile_id=payload["compile_id"],
                client_request_id=payload["client_request_id"],
            )
        except (ProtocolValidationError, TypeError) as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
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
        "/api/v2/projects/{project_id}/runs/{run_id}:cancel",
        include_in_schema=False,
    )
    async def public_cancel_run(
        request: Request,
        project_id: str,
        run_id: str,
        payload: Any = Body(...),
    ) -> Any:
        try:
            combined = {
                "project_id": project_id,
                "run_id": run_id,
                **payload,
            }
            validate_request("cancel_run", combined)
            receipt = await asyncio.to_thread(
                request.app.state.run_execution_v2.cancel,
                project_id,
                run_id,
                after_cursor=payload.get("after_sequence"),
            )
        except (ProtocolValidationError, TypeError) as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        validate_response("cancel_run", 200, receipt)
        return receipt

    @app.post(
        "/api/v2/projects/{project_id}/runs:derive",
        include_in_schema=False,
    )
    async def public_start_derived_run(
        request: Request,
        project_id: str,
        payload: Any = Body(...),
    ) -> Any:
        try:
            combined = {"project_id": project_id, **payload}
            validate_request("start_derived_run", combined)
            receipt = (
                request.app.state.run_execution_v2.start_derived_background(
                    project_id,
                    source_run_id=payload["source_run_id"],
                    compile_id=payload["compile_id"],
                    policy=payload["policy"],
                    node_ids=payload["node_ids"],
                    client_request_id=payload["client_request_id"],
                )
            )
        except (ProtocolValidationError, TypeError) as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
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
        "/api/v2/projects/{project_id}/runs/{run_id}",
        include_in_schema=False,
    )
    async def public_run_projection(
        request: Request,
        project_id: str,
        run_id: str,
    ) -> Any:
        try:
            validate_request(
                "run_projection",
                {"project_id": project_id, "run_id": run_id},
            )
            projection = request.app.state.run_execution_v2.projection(
                project_id,
                run_id,
            )
        except ProtocolValidationError as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        validate_response("run_projection", 200, projection)
        return projection

    @app.get(
        "/api/v2/projects/{project_id}/runs/{run_id}/artifacts/"
        "{artifact_reference}",
        include_in_schema=False,
    )
    def public_v2_artifact(
        request: Request,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> Any:
        try:
            validate_request(
                "artifact_retrieval",
                {
                    "project_id": project_id,
                    "run_id": run_id,
                    "artifact_reference": artifact_reference,
                },
            )
            artifact, body = request.app.state.run_execution_v2.artifact(
                project_id,
                run_id,
                artifact_reference,
            )
        except ProtocolValidationError as error:
            return public_error_response(
                "malformed_request",
                str(error),
                {"field_path": []},
            )
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        content_disposition = (
            f'attachment; filename="{artifact_reference}.bin"'
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
        "/api/v2/projects/{project_id}/runs/{run_id}/events"
    )
    async def public_v2_run_events(
        websocket: WebSocket,
        project_id: str,
        run_id: str,
    ) -> None:
        if not _is_trusted_browser_origin(websocket):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            after_sequence = websocket.query_params.get("after_sequence")
            request_payload: dict[str, Any] = {
                "project_id": project_id,
                "run_id": run_id,
            }
            if after_sequence is not None:
                request_payload["after_sequence"] = after_sequence
            validate_schema(
                "#/$defs/RunEventStreamRequest",
                request_payload,
            )
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
            _, payload = public_error_payload(code, message, details)
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json(payload)
            await websocket.close(code=1008)

    # Project provisioning and opaque input publication are storage controls,
    # not alternate Workflow or Run protocols. Scientific runtime operations
    # remain exclusively under the versioned public bundle above.
    @app.post("/api/projects", include_in_schema=False)
    async def create_project(
        request: Request,
        payload: Any = Body(...),
    ) -> Any:
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"name"}
            or not isinstance(payload["name"], str)
            or not 1 <= len(payload["name"]) <= 256
        ):
            return JSONResponse(
                status_code=422,
                content={
                    "schema_namespace": "protein-workbench-project/v2",
                    "error": {
                        "code": "malformed_request",
                        "message": "Project name is invalid",
                    },
                },
            )
        meta = request.app.state.project_manager.create(payload["name"])
        return {
            "schema_namespace": "protein-workbench-project/v2",
            "id": meta.id,
            "name": meta.name,
            "created_at": meta.created_at,
        }

    @app.post(
        "/api/projects/{project_id}/inputs",
        include_in_schema=False,
    )
    async def upload_input(
        request: Request,
        project_id: str,
        file: UploadFile = File(...),
    ) -> Any:
        manager = request.app.state.project_manager
        try:
            project = manager.load_meta(project_id)
        except ValueError:
            return public_error_response(
                "unsupported_schema_version",
                "Project metadata is not a supported exact v2 artifact",
                {
                    "artifact_kind": "project",
                    "expected_schema_version": "2.1.0",
                    "received_schema_version": "unknown",
                },
            )
        if project is None:
            return JSONResponse(
                status_code=404,
                content={
                    "schema_namespace": "protein-workbench-project/v2",
                    "error": {
                        "code": "project_not_found",
                        "message": "Project was not found",
                    },
                },
            )
        manager.assert_writable(project_id)
        payload = await file.read(MAX_PROJECT_INPUT_BYTES + 1)
        if len(payload) > MAX_PROJECT_INPUT_BYTES:
            raise StoragePathError(
                "file",
                "Uploaded Project input is too large",
            )
        published = manager.publish_input(
            project_id,
            f"input-{uuid.uuid4().hex}",
            payload,
        )
        return {
            "schema_namespace": "protein-workbench-project/v2",
            "filename": file.filename,
            **published,
        }

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
