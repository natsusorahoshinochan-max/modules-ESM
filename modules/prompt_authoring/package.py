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


_PACKAGE_VERSION = "2.1.0"
_DEFAULT_METHOD_VERSION = "2.1.0"
_METHOD_VERSIONS = {
    "prompt_from_structure": "3.0.0",
}
_DEFAULT_NODE_BINDING_VERSION = "3.0.0"
_NODE_BINDING_VERSIONS = {
    "prompt_from_structure": "5.0.0",
}
_OPERATIONS = (
    "add_function_annotation",
    "assemble_protein_prompt",
    "build_residue_layout",
    "edit_residue_layout",
    "insert_masked_residues",
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
    "insert_masked_residues": InsertMaskedResiduesImplementation,
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


def _build(operation: str):
    def factory(context: OperationContext) -> ScientificOperation:
        implementation = _IMPLEMENTATIONS[operation]
        return implementation(context.resources)

    return factory


def _binding(operation: str) -> ExecutionBindingDefinition:
    binding_version = _NODE_BINDING_VERSIONS.get(
        operation,
        _DEFAULT_NODE_BINDING_VERSION,
    )
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
        version=binding_version,
        node_type=ContractIdentity(
            "node_type",
            f"prompt_authoring.{operation}",
            binding_version,
        ),
        method=ContractIdentity(
            "method",
            f"prompt_authoring.{operation}.method",
            _METHOD_VERSIONS.get(operation, _DEFAULT_METHOD_VERSION),
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/factory",
                binding_version,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/availability",
                binding_version,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
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
                    binding_version,
                    {"normalization": "canonical-effective-set-v1"},
                ),
                resolve=randomness_resolvers[operation],
            )
            if operation in randomness_resolvers
            else None
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="prompt_authoring",
    package_version=_PACKAGE_VERSION,
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
