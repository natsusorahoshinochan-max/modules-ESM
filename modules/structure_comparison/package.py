"""The complete active production registration for structure comparison."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Mapping

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ScientificOperationFactory,
    UtilityTransformDefinition,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import (
    OperationContext,
    ScientificOperation,
)

from .contracts import (
    ALIGNMENT_METHODS,
    RMSD_FROM_EVIDENCE_METHOD,
    SEQUENCE_PRIMARY_AFFINE_METHOD,
    STATIC_METHODS,
    STRUCTURE_FIRST_TM_ALIGN_METHOD,
    INSERTED_LOOP_EVALUATION_METHOD,
    THREE_WAY_CONSISTENCY_METHOD,
    TM_SCORE_FROM_EVIDENCE_METHOD,
    VERSION,
)
from .implementation import StructureComparisonImplementation
from .port_types import ALIGNMENT_EVIDENCE_PORT_TYPE
from .inserted_loop_port import INSERTED_LOOP_EVALUATION_PORT_TYPE
from .three_way_port import THREE_WAY_CONSISTENCY_PORT_TYPE


_RMSD_NORMALIZATION = "aligned-CA-mean-square-distance"
_TM_NORMALIZATION = "reference-axis-residue-count"
ALIGNMENT_NODE_VERSION = "5.0.0"
SCORE_NODE_VERSION = "6.0.0"
THREE_WAY_VERSION = "3.0.0"
INSERTED_LOOP_VERSION = "2.0.0"
TM_UTILITY_VERSION = "4.0.0"


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _build(
    operation: str,
    pairing_mode: str | None = None,
) -> Callable[[OperationContext], ScientificOperation]:
    def factory(context: OperationContext) -> ScientificOperation:
        return StructureComparisonImplementation(
            context,
            operation,
            pairing_mode,
        )

    return factory


def _build_three_way(context: OperationContext) -> ScientificOperation:
    from .three_way import ThreeWayConsistencyImplementation

    return ThreeWayConsistencyImplementation(context.method)


def _build_inserted_loop(
    context: OperationContext,
) -> ScientificOperation:
    from .inserted_loop import EvaluateInsertedLoopImplementation

    del context
    return EvaluateInsertedLoopImplementation()


INSERTED_LOOP_BINDING = ExecutionBindingDefinition(
    binding_id="structure_comparison.evaluate_inserted_loop.direct",
    version=INSERTED_LOOP_VERSION,
    node_type=ContractIdentity(
        "node_type",
        "structure_comparison.evaluate_inserted_loop",
        INSERTED_LOOP_VERSION,
    ),
    method=INSERTED_LOOP_EVALUATION_METHOD.identity,
    binding_parameters={},
    execution_route="direct",
    factory=ScientificOperationFactory(
        behavior=BehaviorReference(
            "structure_comparison.evaluate_inserted_loop.direct/factory",
            INSERTED_LOOP_VERSION,
            {"execution_route": "direct"},
        ),
        build=_build_inserted_loop,
    ),
    availability=AvailabilityDeclaration(
        behavior=BehaviorReference(
            "structure_comparison.evaluate_inserted_loop.direct/availability",
            INSERTED_LOOP_VERSION,
            {"observation": "startup"},
        ),
        prerequisites={},
        check=_available,
    ),
    deterministic=True,
    cacheable=True,
    implementation_identity={
        "name": "structure_comparison.evaluate_inserted_loop.direct",
        "source": "repository-owned",
        "candidate_association": "exact-CandidateDataReference",
        "prediction_to_structure_mapping": "exact-residue-order",
        "raw_structure_parsing": False,
        "missing_scoped_evidence": "fail",
    },
)


THREE_WAY_CONSISTENCY_BINDING = ExecutionBindingDefinition(
    binding_id="structure_comparison.classify_three_way_consistency.direct",
    version=THREE_WAY_VERSION,
    node_type=ContractIdentity(
        "node_type",
        "structure_comparison.classify_three_way_consistency",
        THREE_WAY_VERSION,
    ),
    method=THREE_WAY_CONSISTENCY_METHOD.identity,
    binding_parameters={},
    execution_route="direct",
    factory=ScientificOperationFactory(
        behavior=BehaviorReference(
            "structure_comparison.classify_three_way_consistency.direct/factory",
            THREE_WAY_VERSION,
            {"execution_route": "direct"},
        ),
        build=_build_three_way,
    ),
    availability=AvailabilityDeclaration(
        behavior=BehaviorReference(
            "structure_comparison.classify_three_way_consistency.direct/availability",
            THREE_WAY_VERSION,
            {"observation": "startup"},
        ),
        prerequisites={},
        check=_available,
    ),
    deterministic=True,
    cacheable=True,
    implementation_identity={
        "name": "structure_comparison.classify_three_way_consistency.direct",
        "source": "repository-owned",
        "candidate_association": "exact-CandidateDataReference",
        "raw_structure_parsing": False,
        "input_b_factor_interpretation": False,
    },
)


def _tm_score_identity(
    value: object,
    parameters: Mapping[str, Any],
) -> float:
    if parameters:
        raise ValueError("TM-score identity Utility accepts no parameters")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 1
    ):
        raise ValueError("TM-score identity Utility requires [0, 1]")
    return float(value)


def _tm_score_utility(pairing_mode: str) -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id=(
            "structure_comparison.tm_score."
            f"{pairing_mode}.identity"
        ),
        version=TM_UTILITY_VERSION,
        compatible_input_contract={
            "metric": ContractIdentity(
                "metric",
                "structure_comparison.tm_score",
                VERSION,
            ),
            "method": TM_SCORE_FROM_EVIDENCE_METHOD.identity,
            "context_profile": {
                "kind": "pairwise",
                "subject_role": "subject",
                "reference_role": "reference",
                "pairing_mode": pairing_mode,
                "normalization": _TM_NORMALIZATION,
            },
        },
        parameters={},
        behavior=BehaviorReference(
            "structure_comparison.tm_score.identity/transform",
            TM_UTILITY_VERSION,
            {"mapping": "identity"},
        ),
        transform=_tm_score_identity,
    )


def _binding(
    *,
    node_name: str,
    operation: str,
    suffix: str,
    method: Any,
    pairing_mode: str | None = None,
) -> ExecutionBindingDefinition:
    node_id = f"structure_comparison.{node_name}"
    binding_id = f"{node_id}.{suffix}"
    node_version = (
        SCORE_NODE_VERSION
        if operation in {"rmsd", "tm_score"}
        else ALIGNMENT_NODE_VERSION
    )
    produced: tuple[ProducedObservationDefinition, ...] = ()
    if operation in {"rmsd", "tm_score"}:
        assert pairing_mode is not None
        normalization = (
            _RMSD_NORMALIZATION
            if operation == "rmsd"
            else _TM_NORMALIZATION
        )
        produced = (
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=(
                    f"structure_comparison.{operation}.{pairing_mode}"
                ),
                metric=ContractIdentity(
                    "metric",
                    f"structure_comparison.{operation}",
                    VERSION,
                ),
                context_profile={
                    "kind": "pairwise",
                    "subject_role": "subject",
                    "reference_role": "reference",
                    "pairing_mode": pairing_mode,
                    "normalization": normalization,
                },
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="subjects",
                reference_direction="input",
                reference_port="references",
                pairing_direction=(
                    "input"
                    if pairing_mode == "per_subject_counterpart"
                    else None
                ),
                pairing_port=(
                    "pairing"
                    if pairing_mode == "per_subject_counterpart"
                    else None
                ),
                guaranteed_multiplicity="one",
            ),
        )
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        version=node_version,
        node_type=ContractIdentity("node_type", node_id, node_version),
        method=method.identity,
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"{binding_id}/factory",
                node_version,
                {"execution_route": "direct"},
            ),
            build=_build(operation, pairing_mode),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{binding_id}/availability",
                node_version,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": binding_id,
            "source": "repository-owned",
            "candidate_association": "exact-CandidateDataReference",
            "raw_structure_parsing": False,
            "pairing_input": (
                "required"
                if pairing_mode == "per_subject_counterpart"
                else "forbidden"
                if pairing_mode == "fixed_reference"
                else "absent"
            ),
            "pairing_entry_identity": (
                "complete-subject/reference-CandidateDataReference"
                if pairing_mode == "per_subject_counterpart"
                else "not-applicable"
            ),
        },
        produced_observations=produced,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="structure_comparison",
    package_version="7.0.0",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/align_single.yaml"),
        DefinitionResource("definitions/align_fixed_reference.yaml"),
        DefinitionResource("definitions/align_counterparts.yaml"),
        DefinitionResource("definitions/rmsd_fixed_reference.yaml"),
        DefinitionResource("definitions/rmsd_counterparts.yaml"),
        DefinitionResource("definitions/tm_score_fixed_reference.yaml"),
        DefinitionResource("definitions/tm_score_counterparts.yaml"),
        DefinitionResource("definitions/classify_three_way_consistency.yaml"),
        DefinitionResource("definitions/evaluate_inserted_loop.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/rmsd_metric.yaml"),
        DefinitionResource("definitions/tm_score_metric.yaml"),
    ),
    methods=(*ALIGNMENT_METHODS, *STATIC_METHODS),
    utility_transforms=(
        _tm_score_utility("fixed_reference"),
        _tm_score_utility("per_subject_counterpart"),
    ),
    bindings=(
        _binding(
            node_name="align_single",
            operation="align_single",
            suffix="sequence_primary_affine",
            method=SEQUENCE_PRIMARY_AFFINE_METHOD,
        ),
        _binding(
            node_name="align_single",
            operation="align_single",
            suffix="structure_first_tm_align",
            method=STRUCTURE_FIRST_TM_ALIGN_METHOD,
        ),
        _binding(
            node_name="align_fixed_reference",
            operation="align_pairwise",
            suffix="sequence_primary_affine",
            method=SEQUENCE_PRIMARY_AFFINE_METHOD,
            pairing_mode="fixed_reference",
        ),
        _binding(
            node_name="align_counterparts",
            operation="align_pairwise",
            suffix="sequence_primary_affine",
            method=SEQUENCE_PRIMARY_AFFINE_METHOD,
            pairing_mode="per_subject_counterpart",
        ),
        _binding(
            node_name="rmsd_fixed_reference",
            operation="rmsd",
            suffix="from_alignment_evidence",
            method=RMSD_FROM_EVIDENCE_METHOD,
            pairing_mode="fixed_reference",
        ),
        _binding(
            node_name="rmsd_counterparts",
            operation="rmsd",
            suffix="from_alignment_evidence",
            method=RMSD_FROM_EVIDENCE_METHOD,
            pairing_mode="per_subject_counterpart",
        ),
        _binding(
            node_name="tm_score_fixed_reference",
            operation="tm_score",
            suffix="from_alignment_evidence",
            method=TM_SCORE_FROM_EVIDENCE_METHOD,
            pairing_mode="fixed_reference",
        ),
        _binding(
            node_name="tm_score_counterparts",
            operation="tm_score",
            suffix="from_alignment_evidence",
            method=TM_SCORE_FROM_EVIDENCE_METHOD,
            pairing_mode="per_subject_counterpart",
        ),
        THREE_WAY_CONSISTENCY_BINDING,
        INSERTED_LOOP_BINDING,
    ),
    port_types=(
        ALIGNMENT_EVIDENCE_PORT_TYPE,
        THREE_WAY_CONSISTENCY_PORT_TYPE,
        INSERTED_LOOP_EVALUATION_PORT_TYPE,
    ),
)
