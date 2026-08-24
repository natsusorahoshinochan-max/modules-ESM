"""Current public Catalog HTTP route."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request

from core.catalog.model import FrozenCatalog
from protein_workbench_public.catalog_codec import encode_catalog_projection
from protein_workbench_public.http.errors import (
    protocol_error_response,
    public_rest_wire_sources,
)
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    bundle_digest,
    decode_rest_request,
)


def register_catalog_routes(
    app: FastAPI,
    catalog: FrozenCatalog,
    rest_operations: Mapping[str, Any],
) -> None:
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
        payload = encode_catalog_projection(
            catalog.projection(),
            protocol_digest=bundle_digest(),
        )
        return emit_rest_json_success("catalog_snapshot", payload)
