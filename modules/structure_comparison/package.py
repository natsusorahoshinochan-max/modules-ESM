"""The complete active production registration for structure comparison."""

from __future__ import annotations

from core.catalog.result_reading import ResultReaderDefinition
from core.catalog.ui import ModuleUiDefinition, NodeEditorDefinition, ResultViewerDefinition
from .published_reading import read_alignment
from .regional_statistics import RegionStatisticsImplementation, REGION_STATISTICS_PORT_TYPE, read_statistics

from datatypes.observation import PairwiseContextProfile

from core.catalog.observation import ObservationPortSource

from collections.abc import Callable
from typing import Any

from core.catalog.adopted_sources import with_adopted_sources

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ScientificOperationFactory,
    UtilityTransformDefinition,
)
from datatypes.exact_reference import ExactContractReference
from core.catalog.observation import ProducedObservation
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
)
from .implementation import StructureComparisonImplementation
from .metrics import tm_score_identity
from .port_types import ALIGNMENT_EVIDENCE_PORT_TYPE
from .inserted_loop_port import INSERTED_LOOP_EVALUATION_PORT_TYPE
from .three_way_port import THREE_WAY_CONSISTENCY_PORT_TYPE


_RMSD_NORMALIZATION = "aligned-CA-mean-square-distance"
_TM_NORMALIZATION = "reference-axis-residue-count"


def _build(operation: str) -> Callable[[OperationContext], ScientificOperation]:
    def factory(context: OperationContext) -> ScientificOperation:
        return RegionStatisticsImplementation(context) if operation == "region_statistics" else StructureComparisonImplementation(context, operation)

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
    node_type=ExactContractReference(
        "node_type",
        "structure_comparison.evaluate_inserted_loop",
    ),
    method=INSERTED_LOOP_EVALUATION_METHOD.identity,
    binding_parameters={},
    execution_route="direct",
    factory=ScientificOperationFactory(
        behavior=BehaviorReference(
            "structure_comparison.evaluate_inserted_loop.direct/factory",
            {"execution_route": "direct"},
        ),
        build=_build_inserted_loop,
    ),
    availability=AvailabilityDeclaration(
        behavior=BehaviorReference(
            "structure_comparison.evaluate_inserted_loop.direct/availability",
            {"observation": "startup"},
        ),
        prerequisites={},
        check=AvailabilityResult.available,
    ),
    deterministic=True,
    cacheable=True,
)


THREE_WAY_CONSISTENCY_BINDING = ExecutionBindingDefinition(
    binding_id="structure_comparison.classify_three_way_consistency.direct",
    node_type=ExactContractReference(
        "node_type",
        "structure_comparison.classify_three_way_consistency",
    ),
    method=THREE_WAY_CONSISTENCY_METHOD.identity,
    binding_parameters={},
    execution_route="direct",
    factory=ScientificOperationFactory(
        behavior=BehaviorReference(
            "structure_comparison.classify_three_way_consistency.direct/factory",
            {"execution_route": "direct"},
        ),
        build=_build_three_way,
    ),
    availability=AvailabilityDeclaration(
        behavior=BehaviorReference(
            "structure_comparison.classify_three_way_consistency.direct/availability",
            {"observation": "startup"},
        ),
        prerequisites={},
        check=AvailabilityResult.available,
    ),
    deterministic=True,
    cacheable=True,
)


def _tm_score_utility() -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id="structure_comparison.tm_score.explicit_relation.identity",
        compatible_input_contract={
            "metric": ExactContractReference(
                "metric",
                "structure_comparison.tm_score",
            ),
            "method": TM_SCORE_FROM_EVIDENCE_METHOD.identity,
            "context_profile": {
                "kind": "pairwise",
                "subject_role": "subject",
                "reference_role": "reference",
                "pairing_mode": "explicit_relation",
                "normalization": _TM_NORMALIZATION,
            },
        },
        parameters={},
        behavior=BehaviorReference(
            "structure_comparison.tm_score.identity/transform",
            {"mapping": "identity"},
        ),
        transform=tm_score_identity,
    )


def _binding(
    *,
    node_name: str,
    operation: str,
    suffix: str,
    method: Any,
) -> ExecutionBindingDefinition:
    node_id = f"structure_comparison.{node_name}"
    binding_id = f"{node_id}.{suffix}"
    produced: tuple[ProducedObservation, ...] = ()
    if operation in {"rmsd", "tm_score"}:
        normalization = (
            _RMSD_NORMALIZATION
            if operation == "rmsd"
            else _TM_NORMALIZATION
        )
        produced = (
            ProducedObservation(
                output_port="scores",
                output_partition=(
                    f"structure_comparison.{operation}.explicit_relation"
                ),
                metric=ExactContractReference(
                    "metric",
                    f"structure_comparison.{operation}",
                ),
                context_profile=PairwiseContextProfile(
                    subject_role="subject",
                    reference_role="reference",
                    pairing_mode="explicit_relation",
                    normalization=normalization,
                ),
                subject_input="subjects",
                reference_source=ObservationPortSource("input", "references"),
                pairing_source=ObservationPortSource("input", "relation"),
                guaranteed_multiplicity="one",
            ),
        )
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        node_type=ExactContractReference("node_type", node_id,),
        method=method.identity,
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"{binding_id}/factory",
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{binding_id}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        deterministic=True,
        cacheable=True,
        produced_observations=produced,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    result_readers=(
        ResultReaderDefinition("structure_comparison.alignment_evidence", "alignment", read_alignment),
        ResultReaderDefinition("structure_comparison.region_statistics", "region_statistics", read_statistics),
    ),
    ui_extensions=(ModuleUiDefinition(
        extension_id="structure_comparison.regions", resource_package=__package__,
        entry="ui/build/editor.js", styles=(), react_major=19,
        editors=(NodeEditorDefinition("structure_comparison.regions", "选择比较区域", ("structure_comparison.align_pairs",), "RegionEditor"),
                 NodeEditorDefinition("structure_comparison.statistics", "选择统计区域", ("structure_comparison.region_statistics",), "RegionEditor")),
        viewers=(ResultViewerDefinition("structure_comparison.regions", "区域与对齐", "structure_comparison.alignment_evidence", "AlignmentRegions", True),
                 ResultViewerDefinition("structure_comparison.statistics", "区域统计", "structure_comparison.region_statistics", "RegionalStatistics", True)),
    ),),
    package_id="structure_comparison",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/align_pairs.yaml"),
        DefinitionResource("definitions/region_statistics.yaml"),
        DefinitionResource("definitions/rmsd_from_alignments.yaml"),
        DefinitionResource("definitions/tm_score_from_alignments.yaml"),
        DefinitionResource("definitions/classify_three_way_consistency.yaml"),
        DefinitionResource("definitions/evaluate_inserted_loop.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/rmsd_metric.yaml"),
        DefinitionResource("definitions/tm_score_metric.yaml"),
    ),
    methods=(*ALIGNMENT_METHODS, *STATIC_METHODS),
    utility_transforms=(_tm_score_utility(),),
    bindings=(
        _binding(node_name="region_statistics", operation="region_statistics", suffix="direct", method=next(method for method in STATIC_METHODS if method.method_id == "structure_comparison.region_statistics.method")),
        _binding(
            node_name="align_pairs",
            operation="align_pairs",
            suffix="sequence_primary_affine",
            method=SEQUENCE_PRIMARY_AFFINE_METHOD,
        ),
        _binding(
            node_name="align_pairs",
            operation="align_pairs",
            suffix="structure_first_tm_align",
            method=STRUCTURE_FIRST_TM_ALIGN_METHOD,
        ),
        _binding(
            node_name="rmsd_from_alignments",
            operation="rmsd",
            suffix="from_alignment_evidence",
            method=RMSD_FROM_EVIDENCE_METHOD,
        ),
        _binding(
            node_name="tm_score_from_alignments",
            operation="tm_score",
            suffix="from_alignment_evidence",
            method=TM_SCORE_FROM_EVIDENCE_METHOD,
        ),
        THREE_WAY_CONSISTENCY_BINDING,
        INSERTED_LOOP_BINDING,
    ),
    port_types=(
        ALIGNMENT_EVIDENCE_PORT_TYPE,
        REGION_STATISTICS_PORT_TYPE,
        THREE_WAY_CONSISTENCY_PORT_TYPE,
        INSERTED_LOOP_EVALUATION_PORT_TYPE,
    ),
)


MODULE_PACKAGE = with_adopted_sources(MODULE_PACKAGE, (
    ("adopt_alignments", "structure_comparison.alignment_evidence"),
    ("adopt_inserted_loop_evaluation", "structure_comparison.inserted_loop_evaluation"),
    ("adopt_region_statistics", "structure_comparison.region_statistics"),
    ("adopt_three_way_consistency", "structure_comparison.three_way_consistency"),
))
