"""Decode admitted request-local Input bytes without publishing a Project."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from core.project.manager import ProjectInputDescriptor
from protein_workbench_public.protocol import ProtocolValidationError


def prospective_project_inputs(
    values: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[ProjectInputDescriptor, bytes]]:
    result: dict[str, tuple[ProjectInputDescriptor, bytes]] = {}
    for index, value in enumerate(values):
        reference = value["project_input_ref"]
        if reference in result:
            raise ProtocolValidationError(
                f"$.inputs[{index}].project_input_ref", "must be unique",
            )
        payload = base64.b64decode(value["content_base64"])
        result[reference] = (ProjectInputDescriptor(
            project_input_ref=reference, filename=value["filename"],
            size=len(payload),
            content_digest="sha256:" + hashlib.sha256(payload).hexdigest(),
        ), payload)
    return result
