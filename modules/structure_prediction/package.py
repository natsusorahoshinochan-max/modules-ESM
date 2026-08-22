"""Single production registration for structure-prediction confidence."""

from __future__ import annotations

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
    load_method_definitions,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import (
    OperationContext,
    ReadinessCheckInput,
    ReadinessResult,
    ScientificOperation,
)

from .port_types import (
    CONFIDENCE_FACTS_PORT_TYPE,
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
)


VERSION = "2.0.0"
_METRIC_VERSIONS = {
    "structure.ptm": "2.1.0",
    "structure.plddt.per_residue": "3.0.0",
    "structure.plddt.mean_residue": "3.0.0",
    "structure.pae": "3.0.0",
}


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _build(context: OperationContext) -> ScientificOperation:
    from .implementation import MaterializeConfidenceImplementation

    return MaterializeConfidenceImplementation(
        produced_observations=context.produced_observations,
    )


def _produced_observation(
    metric_id: str,
) -> ProducedObservationDefinition:
    has_axis = metric_id != "structure.ptm"
    optional = metric_id in {"structure.ptm", "structure.pae"}
    return ProducedObservationDefinition(
        output_port="observations",
        output_partition="prediction_confidence",
        metric=ContractIdentity(
            "metric",
            metric_id,
            _METRIC_VERSIONS[metric_id],
        ),
        context_profile={"kind": "intrinsic"},
        subject_grain="candidate",
        source_role="subject",
        subject_direction="input",
        subject_port="structure_candidates",
        guaranteed_multiplicity=("zero_or_more" if optional else "one"),
        axis_direction="input" if has_axis else None,
        axis_port="confidence_facts" if has_axis else None,
        method_direction="input",
        method_port="confidence_facts",
    )


MATERIALIZE_CONFIDENCE_BINDING = ExecutionBindingDefinition(
    binding_id="structure_prediction.materialize_confidence.direct",
    version=VERSION,
    node_type=ContractIdentity(
        "node_type",
        "structure_prediction.materialize_confidence",
        VERSION,
    ),
    method=ContractIdentity(
        "method",
        "structure_prediction.materialize_confidence.exact_reference_join",
        VERSION,
    ),
    binding_parameters={},
    execution_route="direct",
    factory=ScientificOperationFactory(
        behavior=BehaviorReference(
            "structure_prediction.materialize_confidence.direct/factory",
            VERSION,
            {"execution_route": "direct"},
        ),
        build=_build,
    ),
    availability=AvailabilityDeclaration(
        behavior=BehaviorReference(
            "structure_prediction.materialize_confidence.direct/availability",
            VERSION,
            {"observation": "startup"},
        ),
        prerequisites={},
        check=_available,
    ),
    readiness=ReadinessDeclaration(
        behavior=BehaviorReference(
            "structure_prediction.materialize_confidence.direct/readiness",
            VERSION,
            {"observation": "per-run"},
        ),
        prerequisites={},
        check=_ready,
    ),
    deterministic=True,
    cacheable=True,
    implementation_identity={
        "name": "structure_prediction.materialize_confidence.direct",
        "source": "repository-owned",
        "join": "complete-exact-reference-bijection",
        "value_transform": "identity-except-declared-mean-plddt",
    },
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
    schema_version="2.1.0",
    package_id="structure_prediction",
    package_version=VERSION,
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
