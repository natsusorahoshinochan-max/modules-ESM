"""The single production registration for prompt authoring."""

from __future__ import annotations

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    EffectiveRandomnessResolver,
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
    ScientificOperation,
)

from .implementation import (
    AddFunctionAnnotationImplementation,
    AssembleProteinPromptImplementation,
    BuildResidueLayoutImplementation,
    EditResidueLayoutImplementation,
    InsertMaskedResiduesImplementation,
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


_OPERATIONS = {
    "add_function_annotation": AddFunctionAnnotationImplementation,
    "assemble_protein_prompt": AssembleProteinPromptImplementation,
    "build_residue_layout": BuildResidueLayoutImplementation,
    "edit_residue_layout": EditResidueLayoutImplementation,
    "insert_masked_residues": InsertMaskedResiduesImplementation,
    "map_residue_track": MapResidueTrackImplementation,
    "override_protein_prompt_track": OverrideProteinPromptTrackImplementation,
    "override_residue_track": OverrideResidueTrackImplementation,
    "prompt_from_structure": PromptFromStructureImplementation,
    "random_insert_masked": RandomInsertMaskedImplementation,
    "random_mask": RandomMaskImplementation,
    "update_prompt_sequence": UpdatePromptSequenceImplementation,
}


def _build(operation: str):
    implementation = _OPERATIONS[operation]

    def factory(context: OperationContext) -> ScientificOperation:
        return implementation(context.resources)

    return factory


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
        node_type=ContractIdentity(
            "node_type",
            f"prompt_authoring.{operation}",
        ),
        method=ContractIdentity(
            "method",
            f"prompt_authoring.{operation}.method",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/factory",
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        deterministic=True,
        cacheable=True,
        effective_randomness_parameters=randomness_parameters,
        effective_randomness_resolver=(
            EffectiveRandomnessResolver(
                behavior=BehaviorReference(
                    f"prompt_authoring.{operation}/effective-randomness",
                    {"normalization": "canonical-effective-set-v1"},
                ),
                resolve=randomness_resolvers[operation],
            )
            if operation in randomness_resolvers
            else None
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="prompt_authoring",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/add_function_annotation.yaml"),
        DefinitionResource("definitions/assemble_protein_prompt.yaml"),
        DefinitionResource("definitions/build_residue_layout.yaml"),
        DefinitionResource("definitions/edit_residue_layout.yaml"),
        DefinitionResource("definitions/insert_masked_residues.yaml"),
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
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(*ALIGNED_TRACK_PORT_TYPES, *PROMPT_PORT_TYPES),
)
