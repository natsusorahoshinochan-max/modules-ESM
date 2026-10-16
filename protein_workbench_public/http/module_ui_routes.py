"""Discover and serve package-owned browser extensions through one public path."""

from dataclasses import asdict
from importlib.resources import files
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response

from core.catalog.model import FrozenCatalog
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request
from .errors import protocol_error_response, public_error_response, public_rest_wire_sources
from .emission import emit_rest_json_success


def register_module_ui_routes(app: FastAPI, catalog: FrozenCatalog) -> None:
    @app.get("/api/v2/module-ui", include_in_schema=False)
    async def manifest(request: Request) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request("module_ui_manifest", query_parameters=query, json_body=body)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        return emit_rest_json_success("module_ui_manifest", {"extensions": [
            {
                "extension_id": extension.extension_id,
                "react_major": extension.react_major,
                "entry_url": f"/api/v2/module-ui/{extension.extension_id}/assets/{extension.entry}",
                "style_urls": [f"/api/v2/module-ui/{extension.extension_id}/assets/{style}" for style in extension.styles],
                "editors": [asdict(editor) for editor in extension.editors],
                "viewers": [asdict(viewer) for viewer in extension.viewers],
                "run_viewers": [asdict(viewer) for viewer in extension.run_viewers],
            }
            for extension in catalog.ui_extensions
        ], "authoring_actions": [action.action_id for action in catalog.authoring_actions], "readers": [{"port_type_id": reader.port_type_id, "kind": reader.kind} for reader in catalog.result_readers]})

    @app.get("/api/v2/module-ui/{extension_id}/assets/{resource_path:path}", include_in_schema=False)
    async def asset(extension_id: str, resource_path: str, request: Request) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request("module_ui_asset", path_parameters={"extension_id": extension_id, "resource_path": resource_path}, query_parameters=query, json_body=body)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        extension = next((item for item in catalog.ui_extensions if item.extension_id == extension_id), None)
        if extension is None or resource_path not in (extension.entry, *extension.styles):
            return public_error_response("module_ui_asset_not_found", "Module UI asset is not declared", {"extension_id": extension_id, "resource_path": resource_path})
        content = files(extension.resource_package).joinpath(resource_path).read_bytes()
        return Response(content, media_type="text/css" if resource_path in extension.styles else "text/javascript", headers={"Cache-Control": "no-cache"})
