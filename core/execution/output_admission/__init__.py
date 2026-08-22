"""Closed Output Admission boundary for raw scientific Operation results."""

from core.execution.output_admission.admission import (
    AdmittedNodeOutput,
    NodeOutputPlan,
    admit_node_output,
)

__all__ = [
    "AdmittedNodeOutput",
    "NodeOutputPlan",
    "admit_node_output",
]
