"""The single production registration for prompt authoring."""

from __future__ import annotations

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    EffectiveRandomnessResolver,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
)

from .implementation import (
    AddFunctionAnnotationImplementation,
    AssembleProteinPromptImplementation,
    BuildResidueLayoutImplementation,
    EditResidueLayoutImplementation,
    MapResidueTrackImplementation,
    OverrideProteinPromptTrackImplementation,
    OverrideResidueTrackImplementation,
    PromptFromStructureImplementation,
    RandomInsertMaskedImplementation,
    RandomMaskImplementation,
    UpdatePromptSequenceImplementation,
)
from .prompt_types import PROMPT_PORT_TYPES
from .stochastic import (
    resolve_random_insert_effective_randomness,
    resolve_random_mask_effective_randomness,
)
from .track_types import ALIGNED_TRACK_PORT_TYPES


_VERSION = "2.0.0"
_OPERATIONS = (
    "add_function_annotation",
    "assemble_protein_prompt",
    "build_residue_layout",
    "edit_residue_layout",
    "map_residue_track",
    "override_protein_prompt_track",
    "override_residue_track",
    "prompt_from_structure",
    "random_insert_masked",
    "random_mask",
    "update_prompt_sequence",
)
_IMPLEMENTATIONS = {
    "add_function_annotation": AddFunctionAnnotationImplementation,
    "assemble_protein_prompt": AssembleProteinPromptImplementation,
    "build_residue_layout": BuildResidueLayoutImplementation,
    "edit_residue_layout": EditResidueLayoutImplementation,
    "map_residue_track": MapResidueTrackImplementation,
    "override_protein_prompt_track": OverrideProteinPromptTrackImplementation,
    "override_residue_track": OverrideResidueTrackImplementation,
    "prompt_from_structure": PromptFromStructureImplementation,
    "random_insert_masked": RandomInsertMaskedImplementation,
    "random_mask": RandomMaskImplementation,
    "update_prompt_sequence": UpdatePromptSequenceImplementation,
}


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(environment: object) -> bool:
    del environment
    return True


def _build(operation: str):
    def factory(**kwargs: object) -> object:
        implementation = _IMPLEMENTATIONS[operation]
        return implementation(kwargs["run_resources"], operation)

    return factory


def _method(operation: str) -> MethodDefinition:
    algorithm_identity = {
        "add_function_annotation": {
            "name": "chain-qualified-function-interval-authoring",
            "interval_indexing": "one-based-inclusive-provider-axis",
            "ordering": "global-start-global-end-label-and-provenance",
            "overlap_policy": "explicit-workflow-choice",
        },
        "assemble_protein_prompt": {
            "name": "validated-residue-aligned-protein-prompt-assembly",
            "track_layout": "exact-effective-residue-layout",
            "optional_tracks": "absent-or-explicitly-nullable",
        },
        "build_residue_layout": {
            "name": "canonical-residue-layout-construction",
            "residue_identity": "<chain>:<one-based-generated-label>",
            "chain_boundary": "ordered-contiguous-chain-blocks",
        },
        "edit_residue_layout": {
            "name": "explicit-residue-identity-reconciliation",
            "mapping_operations": ["delete", "insert", "match"],
            "mapping_indexing": "zero-based-with-negative-unmapped-sentinel",
        },
        "map_residue_track": {
            "name": "explicit-residue-map-conversion",
            "nullable_semantics": "JSON null means unmapped or unspecified",
            "mapping_indexing": "zero-based",
        },
        "override_residue_track": {
            "name": "identity-addressed-track-override",
            "actions": ["clear", "preserve", "replace"],
            "nullable_semantics": "JSON null means unspecified",
        },
        "override_protein_prompt_track": {
            "name": "identity-addressed-protein-prompt-track-override",
            "actions": ["clear", "preserve", "replace"],
            "unaffected_tracks": "byte-equivalent-canonical-values",
        },
        "prompt_from_structure": {
            "name": "canonical-pdb-to-protein-prompt",
            "residue_identity": "chain-residue-number-insertion-code",
            "coordinates": "named-atoms",
            "visibility": "present-coordinate-residues",
        },
        "random_insert_masked": {
            "name": "seeded-chain-local-masked-residue-insertion",
            "sampling": "sha256-boundary-set-digest-counter-modulo-v1",
            "replacement": "with-replacement-across-eligible-boundaries",
            "eligibility": "canonical-unordered-effective-chain-set-v1",
            "inserted_values": "explicit-null-on-every-present-track",
        },
        "random_mask": {
            "name": "seeded-assigned-residue-masking",
            "sampling": "sha256-residue-ranking-v1",
            "replacement": "without-replacement",
            "eligibility": "canonical-unordered-assigned-residue-set-v1",
            "masked_value": "explicit-null",
        },
        "update_prompt_sequence": {
            "name": "generic-protein-prompt-sequence-replacement",
            "preservation": "layout-and-all-unaffected-tracks",
            "residue_identity": "exact-layout-order",
        },
    }[operation]
    return MethodDefinition(
        method_id=f"prompt_authoring.{operation}.method",
        version=_VERSION,
        algorithm_identity=algorithm_identity,
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "residue_identity": "<chain>:<label>",
            "chain_boundary": "contiguous",
        },
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    randomness_parameters = {
        "random_mask": (
            "effective_seed",
            "count",
            "track",
            "eligible_residue_ids",
        ),
        "random_insert_masked": (
            "effective_seed",
            "count",
            "eligible_chain_ids",
        ),
    }.get(operation, ())
    randomness_resolvers = {
        "random_mask": resolve_random_mask_effective_randomness,
        "random_insert_masked": resolve_random_insert_effective_randomness,
    }
    return ExecutionBindingDefinition(
        binding_id=f"prompt_authoring.{operation}.direct",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"prompt_authoring.{operation}",
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"prompt_authoring.{operation}.method",
            _VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/factory",
                _VERSION,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/availability",
                _VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/readiness",
                _VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"prompt_authoring.{operation}.direct",
            "source": "repository-owned",
        },
        effective_randomness_parameters=randomness_parameters,
        effective_randomness_resolver=(
            EffectiveRandomnessResolver(
                behavior=BehaviorReference(
                    f"prompt_authoring.{operation}/effective-randomness",
                    _VERSION,
                    {"normalization": "canonical-effective-set-v1"},
                ),
                resolve=randomness_resolvers[operation],
            )
            if operation in randomness_resolvers
            else None
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="prompt_authoring",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/add_function_annotation.yaml"),
        DefinitionResource("definitions/assemble_protein_prompt.yaml"),
        DefinitionResource("definitions/build_residue_layout.yaml"),
        DefinitionResource("definitions/edit_residue_layout.yaml"),
        DefinitionResource("definitions/map_residue_track.yaml"),
        DefinitionResource(
            "definitions/override_protein_prompt_track.yaml"
        ),
        DefinitionResource("definitions/override_residue_track.yaml"),
        DefinitionResource("definitions/prompt_from_structure.yaml"),
        DefinitionResource("definitions/random_insert_masked.yaml"),
        DefinitionResource("definitions/random_mask.yaml"),
        DefinitionResource("definitions/update_prompt_sequence.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(*ALIGNED_TRACK_PORT_TYPES, *PROMPT_PORT_TYPES),
)
