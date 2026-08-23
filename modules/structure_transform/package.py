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
    CANDIDATE_ASSOCIATION_VERSION,
    CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
    CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
    RESOLVED_AXIS_PORT_TYPE,
    RESOLVED_AXIS_VERSION,
)


_PACKAGE_VERSION = "3.0.0"
_CANDIDATE_NODE_VERSION = "4.0.0"
_STRUCTURE_NODE_VERSION = "4.0.0"
_NORMALIZE_CSH_NODE_VERSION = "5.0.0"
_NORMALIZE_CSH_METHOD_VERSION = "4.0.0"
_RESOLVE_AXIS_METHOD_VERSION = "3.0.0"
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
_NODE_BINDING_VERSIONS = {
    "select_chains": _STRUCTURE_NODE_VERSION,
    "select_candidate_chains": _CANDIDATE_NODE_VERSION,
    "extract_backbone": _STRUCTURE_NODE_VERSION,
    "extract_sequence": _STRUCTURE_NODE_VERSION,
    "extract_sequence_candidates": _CANDIDATE_NODE_VERSION,
    "normalize_csh_parent_span": _NORMALIZE_CSH_NODE_VERSION,
    "normalize_csh_parent_span_candidates": "2.0.0",
    "materialize_candidate_normalizations": "2.0.0",
    "project_single_residue_axis": "2.0.0",
    "resolve_residue_axis": RESOLVED_AXIS_VERSION,
    "resolve_candidate_residue_axes": CANDIDATE_ASSOCIATION_VERSION,
    "backbone_to_structure": _STRUCTURE_NODE_VERSION,
}
_METHOD_VERSIONS = {
    "backbone_to_structure": "4.0.0",
    "select_chains": "3.0.0",
    "select_candidate_chains": "3.0.0",
    "extract_backbone": "3.0.0",
    "extract_sequence": "3.0.0",
    "extract_sequence_candidates": "3.0.0",
    "normalize_csh_parent_span": _NORMALIZE_CSH_METHOD_VERSION,
    "normalize_csh_parent_span_candidates": "1.0.0",
    "materialize_candidate_normalizations": "1.0.0",
    "project_single_residue_axis": "1.0.0",
    "resolve_residue_axis": _RESOLVE_AXIS_METHOD_VERSION,
    "resolve_candidate_residue_axes": _RESOLVE_AXIS_METHOD_VERSION,
}
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
    binding_version = _NODE_BINDING_VERSIONS[operation]
    return ExecutionBindingDefinition(
        binding_id=f"structure_transform.{operation}.direct",
        version=binding_version,
        node_type=ContractIdentity(
            "node_type",
            f"structure_transform.{operation}",
            binding_version,
        ),
        method=ContractIdentity(
            "method",
            f"structure_transform.{operation}.method",
            _METHOD_VERSIONS[operation],
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/factory",
                binding_version,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/availability",
                binding_version,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"structure_transform.{operation}.direct",
            "source": "repository-owned",
        },
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="structure_transform",
    package_version=_PACKAGE_VERSION,
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
