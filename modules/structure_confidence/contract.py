"""Public existing-geometry evaluator slot, owned by this task module."""
from dataclasses import dataclass, field

SLOT = 'workbench.evaluate.structure_confidence'
METHOD = 'SimpleFold 1.6B latent + pLDDT head on the given structure'


@dataclass(frozen=True)
class ConfidenceRequest:
    structure_path: str
    structure_format: str
    positions: tuple[dict, ...]


@dataclass(frozen=True)
class ConfidenceResult:
    positions: tuple[dict, ...]
    plddt: tuple[float, ...]
    method: str = METHOD
    context: dict = field(default_factory=dict)
