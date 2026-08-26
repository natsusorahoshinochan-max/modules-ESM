"""The single production registration for structure transformations."""

from __future__ import annotations

from collections.abc import Callable

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
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
    OperationResources,
    ScientificOperation,
)
from .candidate_transforms import (
    ExtractSequenceCandidatesImplementation,
    MaterializeCandidateNormalizationsImplementation,
    NormalizeCshParentSpanCandidatesImplementation,
    ProjectSingleResidueAxisImplementation,
    ResolveCandidateResidueAxesImplementation,
    SelectCandidateChainsImplementation,
)
from .csh_normalization import NormalizeCshParentSpanImplementation
from .projections import (
    BackboneToStructureImplementation,
    ExtractBackboneImplementation,
    ExtractSequenceImplementation,
    SelectChainsImplementation,
)
from .residue_axis import ResolveResidueAxisImplementation
from .port_types import (
    BACKBONE_STRUCTURE_PORT_TYPE,
    CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
    CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
    CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
    RESOLVED_AXIS_PORT_TYPE,
)


_OPERATIONS = (
    "select_chains",
    "select_candidate_chains",
    "extract_backbone",
    "extract_sequence",
    "extract_sequence_candidates",
    "normalize_csh_parent_span",
    "normalize_csh_parent_span_candidates",
    "materialize_candidate_normalizations",
    "project_single_residue_axis",
    "resolve_residue_axis",
    "resolve_candidate_residue_axes",
    "backbone_to_structure",
)
def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


_OPERATION_IMPLEMENTATIONS: dict[
    str,
    Callable[[OperationResources], ScientificOperation],
] = {
    "select_chains": SelectChainsImplementation,
    "select_candidate_chains": SelectCandidateChainsImplementation,
    "extract_backbone": ExtractBackboneImplementation,
    "extract_sequence": ExtractSequenceImplementation,
    "extract_sequence_candidates": ExtractSequenceCandidatesImplementation,
    "normalize_csh_parent_span": NormalizeCshParentSpanImplementation,
    "normalize_csh_parent_span_candidates": (
        NormalizeCshParentSpanCandidatesImplementation
    ),
    "materialize_candidate_normalizations": (
        MaterializeCandidateNormalizationsImplementation
    ),
    "project_single_residue_axis": ProjectSingleResidueAxisImplementation,
    "resolve_residue_axis": ResolveResidueAxisImplementation,
    "resolve_candidate_residue_axes": (
        ResolveCandidateResidueAxesImplementation
    ),
    "backbone_to_structure": BackboneToStructureImplementation,
}


def _build(
    operation: str,
) -> Callable[[OperationContext], ScientificOperation]:
    implementation = _OPERATION_IMPLEMENTATIONS[operation]

    def factory(context: OperationContext) -> ScientificOperation:
        return implementation(context.resources)

    return factory


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"structure_transform.{operation}.direct",
        node_type=ContractIdentity(
            "node_type",
            f"structure_transform.{operation}",
        ),
        method=ContractIdentity(
            "method",
            f"structure_transform.{operation}.method",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/factory",
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        deterministic=True,
        cacheable=True,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="structure_transform",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/select_chains.yaml"),
        DefinitionResource("definitions/select_candidate_chains.yaml"),
        DefinitionResource("definitions/extract_backbone.yaml"),
        DefinitionResource("definitions/extract_sequence.yaml"),
        DefinitionResource("definitions/extract_sequence_candidates.yaml"),
        DefinitionResource("definitions/normalize_csh_parent_span.yaml"),
        DefinitionResource("definitions/normalize_csh_parent_span_candidates.yaml"),
        DefinitionResource("definitions/materialize_candidate_normalizations.yaml"),
        DefinitionResource("definitions/project_single_residue_axis.yaml"),
        DefinitionResource("definitions/resolve_residue_axis.yaml"),
        DefinitionResource("definitions/resolve_candidate_residue_axes.yaml"),
        DefinitionResource("definitions/backbone_to_structure.yaml"),
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(
        BACKBONE_STRUCTURE_PORT_TYPE,
        MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
        RESOLVED_AXIS_PORT_TYPE,
        CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
        CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
        CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
    ),
)
