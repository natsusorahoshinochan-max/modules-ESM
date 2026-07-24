"""Base class for all workflow modules."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext


class WorkflowModule(ABC):
    """Abstract base class for a workflow module.

    Subclasses must implement definition (property) and run().
    validate() is optional and defaults to no validation warnings.

    Modules that call external subprocesses or network APIs should override
    run_async() with a native async implementation to avoid blocking the
    event loop. The executor always calls run_async(); the default
    implementation delegates to run() in a thread pool.
    """

    @property
    @abstractmethod
    def definition(self) -> ModuleDefinition:
        """The module's definition (ports, parameters, metadata)."""
        ...

    async def run_async(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        """Execute the module asynchronously.

        Default implementation delegates to run() in a thread pool.
        Override with a native async implementation for modules that
        call subprocesses or make network requests.
        """
        return await asyncio.to_thread(self.run, inputs, parameters, context)

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
