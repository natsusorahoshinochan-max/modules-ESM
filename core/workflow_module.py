"""Base class for all workflow modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext


class WorkflowModule(ABC):
    """Abstract base class for a workflow module.

    Subclasses must implement definition (property) and run().
    validate() is optional and defaults to no validation warnings.
    """

    @property
    @abstractmethod
    def definition(self) -> ModuleDefinition:
        """The module's definition (ports, parameters, metadata)."""
        ...

    @abstractmethod
    def run(self, inputs: dict[str, Any], parameters: dict[str, Any],
            context: RunContext) -> dict[str, Any]:
        """Execute the module.

        Args:
            inputs: dict keyed by input port name → upstream output value.
            parameters: dict keyed by parameter name → configured value.
            context: execution context (project dir, node ID, run ID, seed).

        Returns:
            dict keyed by output port name → produced value.
            Must return complete, valid outputs for all declared output ports,
            or raise an exception to fail entirely.
        """
        ...

    def validate(self, inputs: dict[str, Any],
                 parameters: dict[str, Any]) -> list[str]:
        """Validate inputs and parameters before execution.

        Returns a list of warning/error messages (empty = no issues).
        Base implementation returns no warnings.
        """
        return []
