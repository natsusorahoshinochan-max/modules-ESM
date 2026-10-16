"""Public module inventory and lifecycle operations."""
from __future__ import annotations

import base64
from typing import Any

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from core.catalog.errors import CatalogBuildError
from core.execution.ledger import V2RunError
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.errors import protocol_error_response, public_error_response, public_rest_wire_sources
from protein_workbench_public.module_management import ModuleManagementError, ModuleManager
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request


def register_module_routes(app: FastAPI, manager: ModuleManager) -> None:
    @app.get("/api/v2/modules", include_in_schema=False)
    async def list_modules(request: Request) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request("module_inventory", query_parameters=query, json_body=body)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        return emit_rest_json_success("module_inventory", manager.inventory())

    async def mutate(request: Request, operation: str, package_id: str | None = None) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(operation,
                path_parameters={"package_id": package_id} if package_id is not None else None,
                query_parameters=query, json_body=body)
            if operation == "module_enable":
                result = await run_in_threadpool(manager.set_enabled, admitted["enabled_package_ids"])
            elif operation == "module_install":
                result = await run_in_threadpool(manager.install_wheel, admitted["filename"], base64.b64decode(admitted["content_base64"]))
            elif operation == "module_install_bundled":
                result = await run_in_threadpool(manager.install_bundled, admitted["package_id"])
            else:
                result = await run_in_threadpool(manager.uninstall, admitted["package_id"])
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except (ModuleManagementError, CatalogBuildError) as error:
            return public_error_response("module_configuration_rejected", str(error), {})
        except V2RunError as error:
            return public_error_response(error.code, str(error), error.details)
        return emit_rest_json_success(operation, result)

    @app.put("/api/v2/modules", include_in_schema=False)
    async def enable_modules(request: Request) -> Any:
        return await mutate(request, "module_enable")

    @app.post("/api/v2/modules/install", include_in_schema=False)
    async def install_module(request: Request) -> Any:
        return await mutate(request, "module_install")

    @app.post("/api/v2/modules/bundled", include_in_schema=False)
    async def install_bundled(request: Request) -> Any:
        return await mutate(request, "module_install_bundled")

    @app.delete("/api/v2/modules/{package_id}", include_in_schema=False)
    async def uninstall_module(request: Request, package_id: str) -> Any:
        return await mutate(request, "module_uninstall", package_id)
