"""Public module-declared private settings operations."""
from typing import Any
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from core.execution.environment import EnvironmentConfigurationError
from core.execution.ledger import V2RunError
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.errors import protocol_error_response, public_error_response, public_rest_wire_sources
from protein_workbench_public.module_settings import ModuleSettings
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request


def register_module_settings_routes(app: FastAPI, settings: ModuleSettings) -> None:
    @app.get("/api/v2/module-settings", include_in_schema=False)
    async def read_settings(request: Request) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request("module_settings", query_parameters=query, json_body=body)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        return emit_rest_json_success("module_settings", settings.projection())

    @app.patch("/api/v2/module-settings/{binding_id}", include_in_schema=False)
    async def update_settings(request: Request, binding_id: str) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request("update_module_settings", path_parameters={"binding_id": binding_id}, query_parameters=query, json_body=body)
            result = await run_in_threadpool(settings.update, admitted["binding_id"], admitted["values"])
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except EnvironmentConfigurationError as error:
            return public_error_response("module_configuration_rejected", str(error), {})
        except V2RunError as error:
            return public_error_response(error.code, str(error), error.details)
        return emit_rest_json_success("update_module_settings", result)
