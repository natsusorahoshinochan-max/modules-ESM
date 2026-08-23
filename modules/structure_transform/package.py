"""The single production registration for structure transformations."""

from __future__ import annotations

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
    PortTypeDefinition,
)
from core.operation import (
    OperationContext,
    ScientificOperation,
)
from datatypes.structure import ProteinStructure

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
    validate_backbone_structure,
)
from .residue_axis import ResolveResidueAxisImplementation
from .port_types import (
    CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
    CANDIDATE_ASSOCIATION_VERSION,
    CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
    CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
    RESOLVED_AXIS_PORT_TYPE,
    RESOLVED_AXIS_VERSION,
)


_PACKAGE_VERSION = "3.0.0"
_VERSION = "2.1.0"
_BACKBONE_PORT_VERSION = "4.0.0"
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


def _build_select_chains(context: OperationContext) -> ScientificOperation:
    return SelectChainsImplementation(context.resources)


def _build_select_candidate_chains(
    context: OperationContext,
) -> ScientificOperation:
    return SelectCandidateChainsImplementation(context.resources)


def _build_extract_backbone(context: OperationContext) -> ScientificOperation:
    return ExtractBackboneImplementation(context.resources)


def _build_extract_sequence(context: OperationContext) -> ScientificOperation:
    return ExtractSequenceImplementation(context.resources)


def _build_extract_sequence_candidates(
    context: OperationContext,
) -> ScientificOperation:
    return ExtractSequenceCandidatesImplementation(context.resources)


def _build_normalize_csh_parent_span(
    context: OperationContext,
) -> ScientificOperation:
    return NormalizeCshParentSpanImplementation(context.resources)


def _build_normalize_csh_parent_span_candidates(
    context: OperationContext,
) -> ScientificOperation:
    return NormalizeCshParentSpanCandidatesImplementation(context.resources)


def _build_materialize_candidate_normalizations(
    context: OperationContext,
) -> ScientificOperation:
    return MaterializeCandidateNormalizationsImplementation(context.resources)


def _build_project_single_residue_axis(
    context: OperationContext,
) -> ScientificOperation:
    return ProjectSingleResidueAxisImplementation(context.resources)


def _build_resolve_residue_axis(
    context: OperationContext,
) -> ScientificOperation:
    return ResolveResidueAxisImplementation(context.resources)


def _build_resolve_candidate_residue_axes(
    context: OperationContext,
) -> ScientificOperation:
    return ResolveCandidateResidueAxesImplementation(context.resources)


def _build_backbone_to_structure(
    context: OperationContext,
) -> ScientificOperation:
    return BackboneToStructureImplementation(context.resources)


_OPERATION_FACTORIES = {
    "select_chains": _build_select_chains,
    "select_candidate_chains": _build_select_candidate_chains,
    "extract_backbone": _build_extract_backbone,
    "extract_sequence": _build_extract_sequence,
    "extract_sequence_candidates": _build_extract_sequence_candidates,
    "normalize_csh_parent_span": _build_normalize_csh_parent_span,
    "normalize_csh_parent_span_candidates": (
        _build_normalize_csh_parent_span_candidates
    ),
    "materialize_candidate_normalizations": (
        _build_materialize_candidate_normalizations
    ),
    "project_single_residue_axis": _build_project_single_residue_axis,
    "resolve_residue_axis": _build_resolve_residue_axis,
    "resolve_candidate_residue_axes": _build_resolve_candidate_residue_axes,
    "backbone_to_structure": _build_backbone_to_structure,
}


def _binding(operation: str) -> ExecutionBindingDefinition:
    binding_version = _NODE_BINDING_VERSIONS.get(operation, _VERSION)
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
            _METHOD_VERSIONS.get(operation, _VERSION),
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/factory",
                binding_version,
                {"execution_route": "direct"},
            ),
            build=_OPERATION_FACTORIES[operation],
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


def _backbone_to_wire(value: ProteinStructure) -> object:
    return {"pdb_string": value.pdb_string}


def _backbone_from_wire(value: object) -> object:
    if (
        not isinstance(value, dict)
        or set(value) != {"pdb_string"}
        or type(value["pdb_string"]) is not str
    ):
        raise ValueError("backbone wire value is invalid")
    return ProteinStructure(pdb_string=value["pdb_string"])


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
        PortTypeDefinition(
            type_id="structure_transform.backbone_structure",
            version=_BACKBONE_PORT_VERSION,
            validator=BehaviorReference(
                "structure_transform.backbone_structure/validate",
                _BACKBONE_PORT_VERSION,
                {
                    "accepted_value_kind": "protein_structure",
                    "embedded_structure_contract": "protein.structure@4.0.0",
                    "record_contract": {
                        "records": ["ATOM", "TER", "END"],
                        "atoms": ["N", "CA", "C", "O"],
                        "alternate_locations": "resolved",
                        "missing_atoms": "rejected",
                        "chain_breaks": "TER-terminated",
                    },
                },
            ),
            codec=BehaviorReference(
                "structure_transform.backbone_structure/codec",
                _BACKBONE_PORT_VERSION,
                {
                    "canonicalization": "RFC 8785",
                    "pdb_line_endings": "LF",
                },
            ),
            content_identity=BehaviorReference(
                "structure_transform.backbone_structure/content",
                _BACKBONE_PORT_VERSION,
                {"digest": "SHA-256"},
            ),
            runtime_validator=validate_backbone_structure,
            runtime_to_wire=_backbone_to_wire,
            runtime_from_wire=_backbone_from_wire,
        ),
        MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
        RESOLVED_AXIS_PORT_TYPE,
        CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
        CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
        CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
    ),
)
