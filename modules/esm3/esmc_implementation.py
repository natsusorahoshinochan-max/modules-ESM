"""Canonical direct sequence-representation Scientific Operation."""

from __future__ import annotations

from typing import Any

from core import OperationCall
from datatypes import ProteinSequence

from .esmc_adapter import BiohubESMCAdapter


class ESMCRepresentationOperation:
    """Validate canonical inputs around one exact ESMC Adapter call."""

    def __init__(self, adapter: BiohubESMCAdapter) -> None:
        self._adapter = adapter

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if (
            set(call.inputs) != {"sequence"}
            or call.node_parameters
            or call.binding_parameters
        ):
            raise ValueError(
                "direct ESMC representation requires one sequence and no "
                "parameters"
            )
        sequence = call.inputs["sequence"].value
        if type(sequence) is not ProteinSequence:
            raise ValueError(
                "direct ESMC representation requires one ProteinSequence"
            )
        return {"representation": self._adapter.represent(sequence)}
