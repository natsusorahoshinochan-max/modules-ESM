"""ProteinMPNN package: thin adapter around repositories/ProteinMPNN/ ."""

from pathlib import Path
from core.module_definition import ModuleDefinition
from core.module_registry import ModuleRegistry
from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
from modules.proteinmpnn.module_score import ProteinMPNNScoreModule
from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule


def register(registry: ModuleRegistry) -> None:
    base = Path(__file__).parent
    for module_cls in [
        ProteinMPNNDesignModule,
        ProteinMPNNScoreModule,
        ProteinMPNNConstraintsModule,
    ]:
        m = module_cls()
        registry.register(m.definition)
