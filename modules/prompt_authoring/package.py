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
from core.catalog.authoring import (
    AuthoringCapabilityDefinition,
    AuthoringRoleEndpoint,
    AuthoringSourceKind,
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
from datatypes.exact_reference import ExactContractReference

from .implementation import (
    AssembleProteinPromptImplementation,
    BuildResidueLayoutImplementation,
    EditProteinPromptLayoutImplementation,
    MergeProteinPromptSourceImplementation,
    OverrideProteinPromptTrackImplementation,
    PromptFromStructureImplementation,
    RandomInsertMaskedImplementation,
    RandomMaskImplementation,
    ReplaceProteinPromptAnnotationsImplementation,
    UpdatePromptSequenceImplementation,
)
from .prompt_types import PROMPT_PORT_TYPES
from .stochastic import (
    resolve_random_insert_effective_randomness,
    resolve_random_mask_effective_randomness,
)
from .track_types import ALIGNED_TRACK_PORT_TYPES


_OPERATIONS = {
    "assemble_protein_prompt": AssembleProteinPromptImplementation,
    "build_residue_layout": BuildResidueLayoutImplementation,
    "edit_protein_prompt_layout": EditProteinPromptLayoutImplementation,
    "merge_protein_prompt_source": MergeProteinPromptSourceImplementation,
    "override_protein_prompt_track": OverrideProteinPromptTrackImplementation,
    "prompt_from_structure": PromptFromStructureImplementation,
    "random_insert_masked": RandomInsertMaskedImplementation,
    "random_mask": RandomMaskImplementation,
    "replace_protein_prompt_annotations": (
        ReplaceProteinPromptAnnotationsImplementation
    ),
    "update_prompt_sequence": UpdatePromptSequenceImplementation,
}


_PROMPT_MANAGED_NODE_TYPES = tuple(
    ExactContractReference("node_type", f"prompt_authoring.{operation}")
    for operation in _OPERATIONS
)
_SOURCE_MANAGED_NODE_TYPES = tuple(
    ExactContractReference("node_type", contract_id)
    for contract_id in (
        "protein_io.import_structure",
        "structure_transform.select_chains",
        "structure_transform.normalize_csh_parent_span",
        "structure_transform.resolve_residue_axis",
    )
)
_MANAGED_NODE_TYPES = (
    *_PROMPT_MANAGED_NODE_TYPES,
    *_SOURCE_MANAGED_NODE_TYPES,
)


PROTEIN_PROMPT_AUTHORING_CAPABILITY = AuthoringCapabilityDefinition(
    capability_id="protein_prompt.authoring",
    title="编写 ProteinPrompt",
    summary="从空白、序列、结构或已有 Prompt 编写完整 ProteinPrompt。",
    category="prompt_authoring",
    editor_kind="prompt_studio",
    source_kinds=(
        AuthoringSourceKind("blank", "空白"),
        AuthoringSourceKind(
            "fasta",
            "FASTA / ProteinSequence",
            (ExactContractReference("port_type", "protein.sequence"),),
        ),
        AuthoringSourceKind(
            "pdb",
            "PDB / Resolved Structure Residue Axis",
            (
                ExactContractReference(
                    "port_type",
                    "structure_transform.resolved_residue_axis",
                ),
            ),
        ),
        AuthoringSourceKind(
            "protein_prompt",
            "ProteinPrompt",
            (ExactContractReference("port_type", "protein.prompt"),),
        ),
    ),
    exposed_inputs=(
        AuthoringRoleEndpoint(
            "sequence_source",
            ExactContractReference("port_type", "protein.sequence"),
        ),
        AuthoringRoleEndpoint(
            "structure_source",
            ExactContractReference(
                "port_type",
                "structure_transform.resolved_residue_axis",
            ),
        ),
        AuthoringRoleEndpoint(
            "prompt_source",
            ExactContractReference("port_type", "protein.prompt"),
        ),
    ),
    exposed_outputs=(
        AuthoringRoleEndpoint(
            "protein_prompt",
            ExactContractReference("port_type", "protein.prompt"),
        ),
        AuthoringRoleEndpoint(
            "residue_layout",
            ExactContractReference("port_type", "residue.layout"),
        ),
    ),
    managed_node_types=_PROMPT_MANAGED_NODE_TYPES,
    materialized_node_types=_MANAGED_NODE_TYPES,
)


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
        DefinitionResource("definitions/assemble_protein_prompt.yaml"),
        DefinitionResource("definitions/build_residue_layout.yaml"),
        DefinitionResource("definitions/edit_protein_prompt_layout.yaml"),
        DefinitionResource("definitions/merge_protein_prompt_source.yaml"),
        DefinitionResource(
            "definitions/override_protein_prompt_track.yaml"
        ),
        DefinitionResource("definitions/prompt_from_structure.yaml"),
        DefinitionResource("definitions/random_insert_masked.yaml"),
        DefinitionResource("definitions/random_mask.yaml"),
        DefinitionResource(
            "definitions/replace_protein_prompt_annotations.yaml"
        ),
        DefinitionResource("definitions/update_prompt_sequence.yaml"),
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(*ALIGNED_TRACK_PORT_TYPES, *PROMPT_PORT_TYPES),
    authoring_capabilities=(PROTEIN_PROMPT_AUTHORING_CAPABILITY,),
)
