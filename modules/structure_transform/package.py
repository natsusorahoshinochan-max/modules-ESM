"""The single production registration for structure transformations."""

from __future__ import annotations

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.operation import (
    OperationContext,
    ReadinessCheckInput,
    ReadinessResult,
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


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


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


def _method(operation: str) -> MethodDefinition:
    algorithm_identity = {
        "select_chains": {
            "name": "ordered-exact-pdb-chain-selection",
            "chain_identity": "one-alphanumeric-PDB-chain-ID",
            "ordering": "workflow-request-order",
            "multi_model": "reject",
            "coordinate_records": ["ATOM", "HETATM"],
            "polymer_declarations": ["MODRES", "SEQRES"],
            "declaration_selection": "exact-chain-identity",
            "chain_breaks": "canonical-TER-per-retained-segment",
        },
        "select_candidate_chains": {
            "name": "candidate-aware-ordered-pdb-chain-selection",
            "selection": "ordered-exact-pdb-chain-selection",
            "cardinality": "one-child-per-input-parent",
            "lineage": "structure-parent-to-structure-child",
            "ordering": "input-candidate-order",
        },
        "extract_backbone": {
            "name": "resolved-axis-canonical-backbone-projection",
            "input_population": "resolved-structure-residue-axis",
            "retained_atoms": ["N", "CA", "C", "O"],
            "retained_residues": "every-axis-residue",
            "parent_names": "axis-parent-residue-names",
            "coordinates": "axis-selected-named-atom-coordinates",
            "missing_atoms": "axis-complete-backbone-mask-fail-fast",
            "chain_breaks": "canonical-TER-per-axis-segment",
            "serialization": "PDB-v3.3-ATOM-occupancy-1-temperature-0",
        },
        "extract_sequence": {
            "name": "resolved-axis-parent-sequence-projection",
            "input_population": "resolved-structure-residue-axis",
            "sequence": "exact-axis-parent-sequence",
            "residue_correspondence": "exact-axis-residue-identities",
            "raw_PDB_reparse": "forbidden",
        },
        "extract_sequence_candidates": {
            "name": "exact-reference-associated-axis-sequence-projection",
            "extraction": "resolved-axis-parent-sequence-projection",
            "cardinality": "one-child-per-input-Candidate",
            "lineage": "association-subject-to-sequence-child",
            "association": "exact-CandidateDataReference",
            "association_join": "complete-exact-reference-bijection",
            "collection_position": "not-scientific-correspondence",
        },
        "normalize_csh_parent_span": {
            "name": "explicit-CSH-to-SHG-parent-span-normalization",
            "component": "CSH",
            "parent_residues": ["SER", "HIS", "GLY"],
            "parent_numbering": ["observed-1", "observed", "observed+1"],
            "atom_mapping": "closed-exact-19-atom-map",
            "provenance": "typed-normalization-output",
            "missing_or_extra_atoms": "reject",
            "identity_collision": "reject",
            "input_TER_at_exact_parent_span": "remove-as-noncovalent-artifact",
            "output_segment_topology": "continuous-through-expanded-parents",
            "non_CSH_polymer_declarations": "preserve-exact-record-bytes",
            "CSH_MODRES_at_normalized_identity": "remove",
            "CSH_SEQRES": (
                "require-exact-per-chain-component-count-and-expand-to-SER-HIS-GLY"
            ),
            "rewritten_SEQRES": "PDB-v3.3-80-column-13-components-per-record",
        },
        "normalize_csh_parent_span_candidates": {
            "name": "candidate-aware-explicit-CSH-parent-span-normalization",
            "scalar_normalization": "normalize_csh_parent_span.method@4.0.0",
            "cardinality": "one-normalized-child-per-input-Candidate",
            "lineage": "exact-input-structure-parent",
            "normalization_evidence": "subjectless-output-slot-keyed-facts",
            "collection_position": "not-scientific-correspondence",
        },
        "materialize_candidate_normalizations": {
            "name": "exact-normalization-fact-Candidate-materialization",
            "join": "normalization-key-and-admitted-content-digest",
            "candidate_coverage": "complete-bijection",
            "association": "exact-CandidateDataReference",
        },
        "project_single_residue_axis": {
            "name": "singleton-exact-reference-residue-axis-projection",
            "cardinality": "exactly-one-Candidate-and-one-association",
            "join": "exact-CandidateDataReference",
        },
        "resolve_residue_axis": {
            "name": "resolved-protein-residue-axis",
            "source_structure": "preserve-exact-PDB-content",
            "component_classification": "PDB-v3.3-MODRES-SEQRES-and-coordinates",
            "standard_polymer": (
                "include-20-parent-residues-independent-of-record-type"
            ),
            "unknown_ATOM_polymer": "reject-without-parent-contract",
            "MSE": "exact-MODRES-MSE-to-MET-at-same-identity",
            "MSE_SEQRES": "unique-ordered-chain-correspondence",
            "ordinary_nonpolymer": "exclude-and-record-disposition",
            "unknown_modified_polymer": "reject",
            "alternate_locations": "blank-then-A-otherwise-reject",
            "segment_topology": "explicit-TER-and-chain-boundaries",
            "coordinate_access": "identity-associated-selected-atoms",
            "coordinate_masks": ["CA", "complete-N-CA-C-O"],
            "normalization_provenance": "embedded-typed-records",
        },
        "resolve_candidate_residue_axes": {
            "name": "exact-reference-associated-resolved-residue-axes",
            "scalar_resolution": "resolved-protein-residue-axis",
            "association_key": "exact-CandidateDataReference",
            "collection_position": "not-scientific-correspondence",
            "candidate_coverage": "complete-no-missing-duplicate-or-extra",
            "normalization_join": "exact-reference-only",
            "structure_binding": "candidate-content-digest",
        },
        "backbone_to_structure": {
            "name": "explicit-backbone-to-generic-structure-conversion",
            "input_contract": (
                "structure_transform.backbone_structure@4.0.0"
            ),
            "output_contract": "protein.structure@4.0.0",
            "pdb_bytes": "preserved",
            "atom_generation": "none",
        },
    }[operation]
    return MethodDefinition(
        method_id=f"structure_transform.{operation}.method",
        version=_METHOD_VERSIONS.get(operation, _VERSION),
        algorithm_identity=algorithm_identity,
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "format": "PDB-v3.3-fixed-columns",
            "coordinates": "provider-native-decimal-text",
        },
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


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
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/readiness",
                binding_version,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"structure_transform.{operation}.direct",
            "source": "repository-owned",
        },
    )


def _backbone_to_wire(value: object) -> object:
    assert type(value) is ProteinStructure
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
    schema_version="2.1.0",
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
    methods=tuple(_method(operation) for operation in _OPERATIONS),
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
