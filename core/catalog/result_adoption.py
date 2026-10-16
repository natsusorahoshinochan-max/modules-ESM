"""Module declaration for restoring a published value as a workflow input."""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.project.adopted_input import AdoptedSnapshot
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import ObservationContextProfile


@dataclass(frozen=True, slots=True)
class ResultSourceDefinition:
    port_type_id: str
    node_type_id: str
    binding_id: str
    output_port: str = 'value'
    observations: Callable[[bytes], tuple[AdoptedObservation, ...]] | None = None
    dependencies: Callable[[bytes, Iterable[AdoptedSnapshot]], tuple[AdoptedSnapshot, ...]] | None = None


@dataclass(frozen=True, slots=True)
class AdoptedObservation:
    """Module-projected observation meaning retained by a persisted input."""
    output_port: str
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_profile: ObservationContextProfile
    guaranteed_multiplicity: str
