"""Module declaration for restoring a published value as a workflow input."""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

if TYPE_CHECKING:
    from core.project.adopted_input import AdoptedSnapshot
    from core.catalog.model import FrozenCatalog
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
    subject_output_port: str | None = None
    reference_output_port: str | None = None
    pairing_output_port: str | None = None


def with_adopted_definitions(catalog: FrozenCatalog, definitions: tuple[Mapping[str, Any], ...]) -> FrozenCatalog:
    """Resolve saved measurement meanings without restoring an executable provider."""
    from dataclasses import replace
    from core.catalog.declarations import MetricDefinition, MethodDefinition
    from core.catalog.model import CatalogContract
    from datatypes.i_json import thaw_i_json

    if not definitions:
        return catalog
    contracts = {(contract.contract_kind, contract.contract_id): contract for contract in catalog.contracts}
    for saved in definitions:
        kind, identity = saved['contract_kind'], saved['contract_id']
        existing = contracts.get((kind, identity))
        if existing is not None:
            if thaw_i_json(existing.result_identity_descriptor) != thaw_i_json(saved):
                raise ValueError(f'Adopted {kind} {identity} conflicts with the current definition')
            continue
        descriptor = thaw_i_json(saved['descriptor'])
        if kind == 'metric':
            definition = MetricDefinition(metric_id=identity, title=identity, description='', **descriptor)
        elif kind == 'method':
            definition = MethodDefinition(method_id=identity, **descriptor)
        else:
            raise ValueError('Only saved Metric and Method definitions belong to adopted inputs')
        contracts[(kind, identity)] = CatalogContract(kind, identity, definition.descriptor_template(), (), definition)
    return replace(catalog, contracts=tuple(contracts.values()))
