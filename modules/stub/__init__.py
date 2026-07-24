"""Stub Echo module for testing the execution engine."""

from pathlib import Path

from core.module_definition import ModuleDefinition
from core.module_registry import ModuleRegistry


def register(registry: ModuleRegistry) -> None:
    """Register the stub Echo module."""
    definition_path = Path(__file__).parent / "definition.yaml"
    definition = ModuleDefinition.from_yaml(definition_path)
    registry.register(definition)
