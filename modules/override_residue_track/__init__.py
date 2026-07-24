from pathlib import Path
from core.module_definition import ModuleDefinition
from core.module_registry import ModuleRegistry
from modules.override_residue_track.module import OverrideResidueTrackModule

def register(registry: ModuleRegistry) -> None:
    d = ModuleDefinition.from_yaml(Path(__file__).parent / "definition.yaml")
    registry.register(d)
