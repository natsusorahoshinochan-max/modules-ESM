"""Single production registration for structure-prediction confidence."""

from __future__ import annotations

from datatypes.observation import IntrinsicContextProfile

from core.catalog.observation import ObservationPortSource

from core.catalog.adopted_sources import with_adopted_sources

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ScientificOperationFactory,
)
from datatypes.exact_reference import ExactContractReference
from core.catalog.observation import ProducedObservation
from core.catalog.definition_resource import (
    DefinitionResource,
    load_method_definitions,
)
from core.catalog.port_contract import BehaviorReference
from core.operation import (
    OperationContext,
    ScientificOperation,
)

from .port_types import (
    CONFIDENCE_FACTS_PORT_TYPE,
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
)
def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _build(context: OperationContext) -> ScientificOperation:
    from .implementation import MaterializeConfidenceImplementation

    return MaterializeConfidenceImplementation(
        produced_observations=context.produced_observations,
    )


def _produced_observation(
    metric_id: str,
) -> ProducedObservation:
    has_axis = metric_id != "structure.ptm"
    optional = metric_id in {"structure.ptm", "structure.pae"}
    return ProducedObservation(
        output_port="observations",
        output_partition="prediction_confidence",
        metric=ExactContractReference(
            "metric",
            metric_id,
        ),
        context_profile=IntrinsicContextProfile(),
        subject_input="structure_candidates",
        guaranteed_multiplicity=("zero_or_more" if optional else "one"),
        axis_source=(ObservationPortSource("input", "confidence_facts") if has_axis else None),
        method_source=ObservationPortSource("input", "confidence_facts"),
    )


MATERIALIZE_CONFIDENCE_BINDING = ExecutionBindingDefinition(
    binding_id="structure_prediction.materialize_confidence.direct",
    node_type=ExactContractReference(
        "node_type",
        "structure_prediction.materialize_confidence",
    ),
    method=ExactContractReference(
        "method",
        "structure_prediction.materialize_confidence.exact_reference_join",
    ),
    binding_parameters={},
    execution_route="direct",
    factory=ScientificOperationFactory(
        behavior=BehaviorReference(
            "structure_prediction.materialize_confidence.direct/factory",
            {"execution_route": "direct"},
        ),
        build=_build,
    ),
    availability=AvailabilityDeclaration(
        behavior=BehaviorReference(
            "structure_prediction.materialize_confidence.direct/availability",
            {"observation": "startup"},
        ),
        prerequisites={},
        check=_available,
    ),
    deterministic=True,
    cacheable=True,
    produced_observations=tuple(
        _produced_observation(metric_id)
        for metric_id in (
            "structure.ptm",
            "structure.plddt.per_residue",
            "structure.plddt.mean_residue",
            "structure.pae",
        )
    ),
)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="structure_prediction",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/materialize_confidence.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/ptm_metric.yaml"),
        DefinitionResource("definitions/plddt_per_residue_metric.yaml"),
        DefinitionResource("definitions/plddt_mean_residue_metric.yaml"),
        DefinitionResource("definitions/pae_metric.yaml"),
    ),
    port_types=(
        PREDICTION_RESIDUE_AXIS_PORT_TYPE,
        CONFIDENCE_FACTS_PORT_TYPE,
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=(MATERIALIZE_CONFIDENCE_BINDING,),
)


__all__ = [
    "MATERIALIZE_CONFIDENCE_BINDING",
    "MODULE_PACKAGE",
]


MODULE_PACKAGE = with_adopted_sources(MODULE_PACKAGE, (
    ("adopt_confidence", "structure_prediction.confidence_facts"),
))
