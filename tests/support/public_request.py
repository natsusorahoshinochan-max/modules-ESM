"""Bundle-driven request construction for public acceptance clients."""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import quote

from protein_workbench_public.protocol import (
    load_bundle,
    validate_request,
    validate_schema,
)


@dataclass(frozen=True, slots=True)
class PreparedRestRequest:
    method: str
    route: str
    json_body: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class PreparedEventStreamRequest:
    transport: str
    route: str
    message_schema: str


def encode_project_input_content(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _render_route(
    route_template: str,
    payload: dict[str, Any],
) -> tuple[str, set[str]]:
    path_template, separator, query_template = route_template.partition("?")

    def render(template: str) -> str:
        rendered = template
        for field in re.findall(r"{([A-Za-z0-9_]+)}", template):
            rendered = rendered.replace(
                f"{{{field}}}",
                quote(str(payload[field]), safe=""),
            )
        return rendered

    fields = set(re.findall(r"{([A-Za-z0-9_]+)}", route_template))
    route = render(path_template)
    if separator:
        query_parts = [
            part
            for part in query_template.split("&")
            if all(
                field in payload
                for field in re.findall(r"{([A-Za-z0-9_]+)}", part)
            )
        ]
        if query_parts:
            route = f"{route}?{'&'.join(render(part) for part in query_parts)}"
    return route, fields


def prepare_rest_request(
    operation_id: str,
    payload: dict[str, Any],
) -> PreparedRestRequest:
    validate_request(operation_id, payload)
    operation = load_bundle()["rest_operations"][operation_id]
    route, route_fields = _render_route(operation["route"], payload)
    body = {
        name: copy.deepcopy(value)
        for name, value in payload.items()
        if name not in route_fields
    }
    return PreparedRestRequest(
        method=operation["method"],
        route=route,
        json_body=body or None,
    )


def prepare_run_event_stream_request(
    payload: dict[str, Any],
) -> PreparedEventStreamRequest:
    stream = load_bundle()["run_event_stream"]
    validate_schema(stream["request_schema"], payload)
    route, _ = _render_route(stream["route"], payload)
    return PreparedEventStreamRequest(
        transport=stream["transport"],
        route=route,
        message_schema=stream["message_schema"],
    )
