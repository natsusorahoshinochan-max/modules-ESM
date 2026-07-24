"""Stub Echo module for testing the execution engine."""

from pathlib import Path

from core.module_definition import ModuleDefinition
from core.module_registry import ModuleRegistry
from modules.stub.echo_module import EchoModule


def register(registry: ModuleRegistry) -> None:
    """Register the stub Echo module definition."""
    definition_path = Path(__file__).parent / "definition.yaml"
    definition = ModuleDefinition.from_yaml(definition_path)
    registry.register(definition)


__all__ = ["EchoModule", "register"]
