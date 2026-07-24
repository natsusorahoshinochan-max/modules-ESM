from pathlib import Path
from core.module_definition import ModuleDefinition
from core.module_registry import ModuleRegistry
from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule

def register(registry: ModuleRegistry) -> None:
    d = ModuleDefinition.from_yaml(Path(__file__).parent / "definition.yaml")
    registry.register(d)
