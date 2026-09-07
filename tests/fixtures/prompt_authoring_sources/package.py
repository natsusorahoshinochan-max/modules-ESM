"""Independent typed values for prompt-authoring Contract Test Kit cases."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
)
from core.operation import (
    OperationCall,
    OperationContext,
    ReadinessResult,
)
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotationTrack,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import (
    NamedAtomCoordinates,
    ProteinStructure,
)
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from modules.structure_transform.residue_axis import resolve_residue_axis


_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_COORDINATES = NamedAtomCoordinates.from_mapping(
    {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)}
)


def _atom(
    serial: int,
    atom_name: str,
    residue_name: str,
    chain_id: str,
    residue_number: int,
    *,
    x: float,
) -> str:
    return (
        f"ATOM  {serial:5d} {atom_name:^4} {residue_name:>3} "
        f"{chain_id}{residue_number:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}"
        f"{1.0:6.2f}{20.0:6.2f}          {atom_name[0]:>2}  "
    )


def _annotations(
    records: list[dict[str, object]] | None = None,
) -> tuple[FunctionAnnotation, ...]:
    return tuple(
        FunctionAnnotation(**record)
        for record in (records or [])
    )


class _Source:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            inputs
            or set(node_parameters) != {"fixture"}
            or binding_parameters
        ):
            raise ValueError("prompt-authoring source accepts no values")
        with self._run_resources.engine_invocation():
            fixture = node_parameters["fixture"]
            source = ResidueLayout(["A:1", "A:2", "B:1"])
            source_track = ResidueTrack(source, ("A", "G", "S"))
            source_secondary_structure_track = ResidueTrack(
                source,
                ("H", "E", "C"),
            )
            source_structure_track = ResidueTrack(
                source,
                (_COORDINATES, None, None),
            )
            source_sasa_track = ResidueTrack(source, (12.5, None, 30.0))
            function_annotations = _annotations(
                [{
                    "label": "binding_site",
                    "start_residue_id": "A:1",
                    "end_residue_id": "A:2",
                }]
            )
            sequence_value = "AGS"
            protein_sequence_value = "WFC"
            if fixture == "annotation-overlap":
                function_annotations = _annotations([
                    {
                        "label": "binding_site",
                        "start_residue_id": "A:1",
                        "end_residue_id": "A:2",
                    },
                    {
                        "label": "active_site",
                        "start_residue_id": "A:2",
                        "end_residue_id": "A:2",
                    },
                ])
            elif fixture == "annotation-out-of-order":
                function_annotations = _annotations([
                    {
                        "label": "chain_b_site",
                        "start_residue_id": "B:1",
                        "end_residue_id": "B:1",
                    },
                    {
                        "label": "chain_a_site",
                        "start_residue_id": "A:1",
                        "end_residue_id": "A:1",
                    },
                ])
            elif fixture == "annotation-cross-chain":
                function_annotations = _annotations([
                    {
                        "label": "cross_chain",
                        "start_residue_id": "A:2",
                        "end_residue_id": "B:1",
                    },
                ])
            elif fixture == "annotation-allow":
                function_annotations = _annotations([
                    {
                        "label": "binding_site",
                        "start_residue_id": "A:1",
                        "end_residue_id": "A:2",
                    },
                ])
            elif fixture == "prompt-illegal-sequence":
                sequence_value = "A?S"
            elif fixture == "3gb1-intent":
                sequence_value = (
                    "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEW"
                    "TYDDATKTFTVTE"
                )
                protein_sequence_value = sequence_value
                source = ResidueLayout(
                    [f"A:{index}" for index in range(1, 57)]
                )
                source_track = ResidueTrack(source, tuple(sequence_value))
                source_structure_track = ResidueTrack(
                    source,
                    tuple(None for _ in range(56)),
                )
                source_secondary_structure_track = ResidueTrack(
                    source,
                    tuple("C" for _ in range(56)),
                )
                source_sasa_track = ResidueTrack(
                    source,
                    tuple(None for _ in range(56)),
                )
                function_annotations = _annotations()
            elif fixture == "insertion-identity-collision":
                sequence_value = "A"
                protein_sequence_value = "A"
                source = ResidueLayout(["A:masked.1.1"])
                source_track = ResidueTrack(source, ("A",))
                source_structure_track = ResidueTrack(source, (None,))
                source_secondary_structure_track = ResidueTrack(
                    source,
                    ("C",),
                )
                source_sasa_track = ResidueTrack(source, (None,))
                function_annotations = _annotations()
            if fixture == "adapter-boundary":
                source_secondary_structure_track = ResidueTrack(
                    source,
                    ("H", "E", None),
                )
            if fixture == "source-track-length-drift":
                source_track = ResidueTrack(source, ("A", "G"))
            structure = ProteinStructure("\n".join((
                _atom(1, "N", "ALA", "A", 1, x=0.0),
                _atom(2, "CA", "ALA", "A", 1, x=1.0),
                _atom(3, "N", "GLY", "A", 2, x=2.0),
                _atom(4, "CA", "GLY", "A", 2, x=3.0),
                "TER",
                _atom(5, "N", "SER", "B", 1, x=4.0),
                _atom(6, "CA", "SER", "B", 1, x=5.0),
                "TER",
                "END",
                "",
            )))
            if fixture == "2emo":
                structure = ProteinStructure(
                    (
                        _PROJECT_ROOT
                        / "examples"
                        / "v2"
                        / "structures"
                        / "2EMO.pdb"
                    ).read_text(),
                )
                normalized, normalizations = normalize_csh_parent_span(
                    structure
                )
                resolved_residue_axis = resolve_residue_axis(
                    normalized,
                    normalizations,
                )
            elif fixture == "5g53":
                structure = ProteinStructure(
                    (
                        _PROJECT_ROOT
                        / "examples"
                        / "v2"
                        / "structures"
                        / "5G53.pdb"
                    ).read_text(),
                )
                resolved_residue_axis = resolve_residue_axis(structure)
            else:
                resolved_residue_axis = resolve_residue_axis(structure)
        return {
            "source_sequence_track": source_track,
            "source_structure_track": source_structure_track,
            "source_secondary_structure_track": (
                source_secondary_structure_track
            ),
            "source_sasa_track": source_sasa_track,
            "function_annotations": FunctionAnnotationTrack(
                source,
                function_annotations,
            ),
            "protein_prompt": ProteinPrompt(
                layout=source,
                sequence=tuple(source_track.values),
                coordinates=tuple(source_structure_track.values),
                secondary_structure=tuple(
                    source_secondary_structure_track.values
                ),
                sasa=tuple(source_sasa_track.values),
                function_annotations=function_annotations,
            ),
            "protein_sequence": ProteinSequence(
                (
                    "WF"
                    if fixture == "sequence-length-drift"
                    else (
                        "W?C"
                        if fixture == "sequence-illegal-symbol"
                        else protein_sequence_value
                    )
                ),
                (
                    ["A:2", "A:1", "B:1"]
                    if fixture == "sequence-identity-drift"
                    else (
                        ["A:1", "A:2"]
                        if fixture == "sequence-length-drift"
                        else list(source.residue_ids or ())
                    )
                ),
            ),
            "structure": structure,
            "resolved_residue_axis": resolved_residue_axis,
        }


def _factory(context: OperationContext) -> object:
    return _Source(context.resources)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="contract_test.prompt_authoring_sources",
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.prompt_authoring_values.method",
            algorithm_identity={"name": "deterministic-fixture"},
            model_identity={"kind": "none"},
            featurization_identity={"kind": "identity-complete-layouts"},
            scale_contract={"kind": "identity"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.prompt_authoring_values.direct",
            node_type=ContractIdentity(
                "node_type",
                "contract_test.prompt_authoring_values"),
            method=ContractIdentity(
                "method",
                "contract_test.prompt_authoring_values.method"),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.prompt_authoring_values/factory",
                    {},
                ),
                build=_factory,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.prompt_authoring_values/availability",
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.prompt_authoring_values/readiness",
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True),
    ),
)
