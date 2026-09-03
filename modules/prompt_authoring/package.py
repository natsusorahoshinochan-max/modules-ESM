"""The single production registration for prompt authoring."""

from __future__ import annotations

from collections.abc import Mapping

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
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
from core.catalog.port_contract import BehaviorReference
from core.operation import OperationCall, ScientificOperation
from datatypes.exact_reference import ExactContractReference
from datatypes.prompt import FunctionAnnotationTrack, ProteinPrompt
from datatypes.residue import ResidueTrack
from datatypes.sequence import ProteinSequence
from datatypes.structure import ResolvedStructureResidueAxis

from .prompt_types import PROMPT_PORT_TYPES
from .recipe import apply_prompt_recipe


class _AuthorOperation(ScientificOperation):
    """Applies the authoring document through the single recipe."""

    def execute(self, call: OperationCall) -> dict[str, object]:
        inputs = call.inputs
        prompt = apply_prompt_recipe(
            sequence_source=_optional_value(inputs, "sequence_source", ProteinSequence),
            structure_source=_optional_value(
                inputs, "structure_source", ResolvedStructureResidueAxis
            ),
            prompt_source=_optional_value(inputs, "prompt_source", ProteinPrompt),
            merge_sources=_many_values(inputs, "merge_sources", ProteinPrompt),
            document=call.node_parameters["document"],
        )
        return {"protein_prompt": prompt}


class _DecomposeOperation(ScientificOperation):
    """Splits a Prompt into authoritative-layout-aligned carriers."""

    def execute(self, call: OperationCall) -> dict[str, object]:
        prompt: ProteinPrompt = call.inputs["protein_prompt"].value
        layout = prompt.layout
        ss = prompt.secondary_structure
        sasa = prompt.sasa
        return {
            "sequence": ResidueTrack(layout, prompt.sequence),
            "coordinates": ResidueTrack(layout, prompt.coordinates),
            "secondary_structure": (
                None if ss is None else ResidueTrack(layout, ss)
            ),
            "sasa": None if sasa is None else ResidueTrack(layout, sasa),
            "function_annotations": FunctionAnnotationTrack(
                layout, prompt.function_annotations
            ),
        }


class _AssembleOperation(ScientificOperation):
    """Assembles a Prompt from exactly-aligned conditioning carriers."""

    def execute(self, call: OperationCall) -> dict[str, object]:
        inputs = call.inputs
        sequence_track: ResidueTrack = inputs["sequence"].value
        coordinates_track: ResidueTrack = inputs["coordinates"].value
        ss_port = inputs.get("secondary_structure")
        sasa_port = inputs.get("sasa")
        fa_track: FunctionAnnotationTrack = inputs["function_annotations"].value
        layout = sequence_track.layout
        if coordinates_track.layout != layout:
            raise ValueError("assemble inputs must share one ResidueLayout")
        if ss_port is not None and ss_port.value is not None:
            if ss_port.value.layout != layout:
                raise ValueError("assemble inputs must share one ResidueLayout")
        if sasa_port is not None and sasa_port.value is not None:
            if sasa_port.value.layout != layout:
                raise ValueError("assemble inputs must share one ResidueLayout")
        if fa_track.layout != layout:
            raise ValueError("assemble inputs must share one ResidueLayout")
        prompt = apply_prompt_recipe_assemble(
            layout=layout,
            sequence_track=sequence_track,
            coordinates_track=coordinates_track,
            secondary_structure_track=None if ss_port is None else ss_port.value,
            sasa_track=None if sasa_port is None else sasa_port.value,
            annotation_track=fa_track,
        )
        return {"protein_prompt": prompt}


def _optional_value(
    inputs: Mapping[str, object],
    name: str,
    expected_type: type,
) -> object | None:
    port = inputs.get(name)
    if port is None or not port:
        return None
    value = port.value
    if not isinstance(value, expected_type):
        raise ValueError(f"input {name!r} has an unexpected value type")
    return value


def _many_values(
    inputs: Mapping[str, object],
    name: str,
    expected_type: type,
) -> tuple[object, ...]:
    port = inputs.get(name)
    if port is None or not port:
        return ()
    values = port.value
    if not isinstance(values, tuple):
        raise ValueError(f"input {name!r} must carry many values")
    for value in values:
        if not isinstance(value, expected_type):
            raise ValueError(f"input {name!r} has an unexpected value type")
    return values


def apply_prompt_recipe_assemble(
    *,
    layout,
    sequence_track: ResidueTrack,
    coordinates_track: ResidueTrack,
    secondary_structure_track: ResidueTrack | None,
    sasa_track: ResidueTrack | None,
    annotation_track: FunctionAnnotationTrack,
) -> ProteinPrompt:
    """Assemble one Prompt from exact-layout conditioning carriers."""
    from .prompts import assemble_protein_prompt

    return assemble_protein_prompt(
        layout,
        {
            "sequence": sequence_track,
            "coordinates": coordinates_track,
            "secondary_structure": secondary_structure_track,
            "sasa": sasa_track,
        },
        tuple(annotation_track.annotations),
    )


_OPERATIONS = {
    "prompt_authoring.author": _AuthorOperation,
    "prompt_authoring.decompose": _DecomposeOperation,
    "prompt_authoring.assemble": _AssembleOperation,
}


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
    ),
)


def _build(operation_id: str) -> ScientificOperationFactory:
    operation_type = _OPERATIONS[operation_id]

    def factory(context: object) -> ScientificOperation:
        return operation_type()

    return ScientificOperationFactory(
        behavior=BehaviorReference(
            f"{operation_id}/factory",
            {"execution_route": "direct"},
        ),
        build=factory,
    )


# The author node's effective randomness lives inside the nested ``document``
# node parameter (``document.random_operations[*].seed``); the flat resolver
# mechanism cannot address nested fields cleanly, so the seed-derived
# effective randomness is computed inside :func:`recipe.apply_prompt_recipe`
# from the document seed plus the resolved layout/inputs. We still declare the
# document as the effective randomness parameter so cache keys remain
# reproducible, and the method identity documents the derivation.
_EFFECTIVE_RANDOMNESS_PARAMETERS: dict[str, tuple[str, ...]] = {
    "prompt_authoring.author": ("document",),
}


def _binding(
    operation_id: str,
    *,
    effective_randomness_parameters: tuple[str, ...] = (),
) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"{operation_id}.direct",
        node_type=ContractIdentity("node_type", operation_id),
        method=ContractIdentity("method", f"{operation_id}.method"),
        binding_parameters={},
        execution_route="direct",
        factory=_build(operation_id),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{operation_id}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        deterministic=True,
        cacheable=True,
        effective_randomness_parameters=tuple(effective_randomness_parameters),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="prompt_authoring",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/prompt_authoring.author.yaml"),
        DefinitionResource("definitions/prompt_authoring.decompose.yaml"),
        DefinitionResource("definitions/prompt_authoring.assemble.yaml"),
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(
        _binding(
            operation_id,
            effective_randomness_parameters=_EFFECTIVE_RANDOMNESS_PARAMETERS.get(
                operation_id, ()
            ),
        )
        for operation_id in _OPERATIONS
    ),
    port_types=PROMPT_PORT_TYPES,
    authoring_capabilities=(PROTEIN_PROMPT_AUTHORING_CAPABILITY,),
)
