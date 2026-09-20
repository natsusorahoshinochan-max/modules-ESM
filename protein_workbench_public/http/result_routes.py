"""Public read-only paging and detail projections for published Candidates."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request

from core.execution.ledger import V2RunError
from core.execution.results.browser import ResultBrowser
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.errors import (
    protocol_error_response, public_error_response, public_rest_wire_sources,
)
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request


def register_result_routes(
    app: FastAPI, browser: ResultBrowser, operations: Mapping[str, Any],
) -> None:
    @app.post(operations["result_collection"]["route"], include_in_schema=False)
    async def result_collection(request: Request, project_id: str, run_id: str) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "result_collection",
                path_parameters={"project_id": project_id, "run_id": run_id},
                query_parameters=query, json_body=body,
            )
            result = await asyncio.to_thread(browser.page, **admitted)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(error.code, str(error), error.details)
        return emit_rest_json_success("result_collection", result)

    @app.post(operations["result_candidate"]["route"], include_in_schema=False)
    async def result_candidate(request: Request, project_id: str, run_id: str) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "result_candidate",
                path_parameters={"project_id": project_id, "run_id": run_id},
                query_parameters=query, json_body=body,
            )
            result = await asyncio.to_thread(browser.candidate, **admitted)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(error.code, str(error), error.details)
        return emit_rest_json_success("result_candidate", result)
