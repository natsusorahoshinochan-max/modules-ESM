"""Canonical direct sequence-representation Scientific Operation."""

from __future__ import annotations

from typing import Any

from core.operation import (
    OperationCall,
)

from .esmc_adapter import BiohubESMCAdapter


class ESMCRepresentationOperation:
    """Apply one exact ESMC Method through its concrete Adapter."""

    def __init__(self, adapter: BiohubESMCAdapter) -> None:
        self._adapter = adapter

    def execute(self, call: OperationCall) -> dict[str, Any]:
        sequence = call.inputs["sequence"].value
        return {"representation": self._adapter.represent(sequence)}
