"""FastAPI construction and assembly for the current public protocol."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import Response

from core.catalog.model import FrozenCatalog
from core.project.manager import ProjectManager
from core.run_execution_v2 import V2RunService
from core.workflow.authoring import WorkflowAuthoringService
from protein_workbench_public.http.catalog_routes import (
    register_catalog_routes,
)
from protein_workbench_public.http.errors import (
    install_error_handlers,
    protocol_error_response,
    public_rest_wire_sources,
)
from protein_workbench_public.http.project_routes import (
    register_project_routes,
)
from protein_workbench_public.http.run_routes import register_run_routes
from protein_workbench_public.http.workflow_routes import (
    register_workflow_routes,
)
from protein_workbench_public.protocol import (
    REST_BODY_ABSENT,
    ProtocolValidationError,
    bundle_bytes,
    bundle_digest,
    load_bundle,
)


def create_http_app(
    catalog: FrozenCatalog,
    projects: ProjectManager,
    authoring: WorkflowAuthoringService,
    runtime: V2RunService,
    *,
    wait_for_workers_on_shutdown: bool = True,
) -> FastAPI:
    """Assemble routes around already-constructed application interfaces."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        yield
        if wait_for_workers_on_shutdown:
            await asyncio.to_thread(runtime.shutdown)

    app = FastAPI(
        title="Protein Workbench",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.project_manager = projects
    app.state.frozen_catalog = catalog
    app.state.workflow_authoring = authoring
    app.state.run_execution_v2 = runtime

    install_error_handlers(app)
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

    register_catalog_routes(app, catalog, rest_operations)
    register_project_routes(app, projects, rest_operations)
    register_workflow_routes(app, authoring, rest_operations)
    register_run_routes(app, runtime, rest_operations, run_event_stream)
    return app
