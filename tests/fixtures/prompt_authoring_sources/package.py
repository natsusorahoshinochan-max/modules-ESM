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
    FunctionAnnotations,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from modules.prompt_authoring.domain import AlignedResidueTrack
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from modules.structure_transform.residue_axis import resolve_residue_axis


_VERSION = "2.1.0"
_NODE_BINDING_VERSION = "4.0.0"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
) -> FunctionAnnotations:
    return FunctionAnnotations(
        [
            FunctionAnnotation(**record)
            for record in (records or [])
        ]
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
            source = ResidueLayout(
                chain_id="A,B",
                length=3,
                residue_ids=["A:1", "A:2", "B:1"],
            )
            target = ResidueLayout(
                chain_id="A,B",
                length=3,
                residue_ids=["A:1", "A:new", "B:1"],
            )
            residue_map = ResidueMap(
                source_layout=source,
                target_layout=target,
                mappings=[
                    (0, 0, "match"),
                    (-1, 1, "insert"),
                    (2, 2, "match"),
                    (1, -1, "delete"),
                ],
            )
            source_track = AlignedResidueTrack(
                source,
                ("A", "G", "S"),
            )
            source_secondary_structure_track = AlignedResidueTrack(
                source,
                ("H", "E", "-"),
            )
            visibility_track = AlignedResidueTrack(
                source,
                (True, True, False),
            )
            source_structure_track = AlignedResidueTrack(
                source,
                (
                    {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)},
                    None,
                    {"CA": (2.0, 0.0, 0.0)},
                ),
            )
            source_sasa_track = AlignedResidueTrack(
                source,
                (12.5, None, 30.0),
            )
            function_annotations = _annotations(
                [{
                    "label": "binding_site",
                    "start": 1,
                    "end": 2,
                    "chain_id": "A",
                    "start_residue_id": "A:1",
                    "end_residue_id": "A:2",
                    "overlap_policy": "reject",
                }]
            )
            sequence_value = "AGS"
            protein_sequence_value = "WFC"
            if fixture == "annotation-overlap":
                function_annotations = _annotations([
                    {
                        "label": "binding_site",
                        "start": 1,
                        "end": 2,
                        "chain_id": "A",
                        "start_residue_id": "A:1",
                        "end_residue_id": "A:2",
                        "overlap_policy": "reject",
                    },
                    {
                        "label": "active_site",
                        "start": 2,
                        "end": 2,
                        "chain_id": "A",
                        "start_residue_id": "A:2",
                        "end_residue_id": "A:2",
                        "overlap_policy": "reject",
                    },
                ])
            elif fixture == "annotation-out-of-order":
                function_annotations = _annotations([
                    {
                        "label": "chain_b_site",
                        "start": 3,
                        "end": 3,
                        "chain_id": "B",
                        "start_residue_id": "B:1",
                        "end_residue_id": "B:1",
                        "overlap_policy": "allow",
                    },
                    {
                        "label": "chain_a_site",
                        "start": 1,
                        "end": 1,
                        "chain_id": "A",
                        "start_residue_id": "A:1",
                        "end_residue_id": "A:1",
                        "overlap_policy": "allow",
                    },
                ])
            elif fixture == "annotation-cross-chain":
                function_annotations = _annotations([
                    {
                        "label": "cross_chain",
                        "start": 2,
                        "end": 3,
                        "chain_id": "A",
                        "start_residue_id": "A:2",
                        "end_residue_id": "B:1",
                        "overlap_policy": "reject",
                    },
                ])
            elif fixture == "annotation-allow":
                function_annotations = _annotations([
                    {
                        "label": "binding_site",
                        "start": 1,
                        "end": 2,
                        "chain_id": "A",
                        "start_residue_id": "A:1",
                        "end_residue_id": "A:2",
                        "overlap_policy": "allow",
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
                    chain_id="A",
                    length=56,
                    residue_ids=[
                        f"A:{index}" for index in range(1, 57)
                    ],
                )
                target = source
                source_track = AlignedResidueTrack(
                    source,
                    tuple(sequence_value),
                )
                source_structure_track = AlignedResidueTrack(
                    source,
                    tuple(None for _ in range(56)),
                )
                visibility_track = AlignedResidueTrack(
                    source,
                    tuple(None for _ in range(56)),
                )
                source_secondary_structure_track = AlignedResidueTrack(
                    source,
                    tuple("-" for _ in range(56)),
                )
                source_sasa_track = AlignedResidueTrack(
                    source,
                    tuple(None for _ in range(56)),
                )
                residue_map = ResidueMap(
                    source_layout=source,
                    target_layout=target,
                    mappings=[
                        (index, index, "match")
                        for index in range(56)
                    ],
                )
                function_annotations = _annotations()
            elif fixture == "insertion-identity-collision":
                sequence_value = "A"
                protein_sequence_value = "A"
                source = ResidueLayout(
                    chain_id="A",
                    length=1,
                    residue_ids=["A:masked.1.1"],
                )
                target = source
                source_track = AlignedResidueTrack(source, ("A",))
                source_structure_track = AlignedResidueTrack(source, (None,))
                visibility_track = AlignedResidueTrack(source, (True,))
                source_secondary_structure_track = AlignedResidueTrack(
                    source,
                    ("-",),
                )
                source_sasa_track = AlignedResidueTrack(source, (None,))
                residue_map = ResidueMap(
                    source_layout=source,
                    target_layout=target,
                    mappings=[(0, 0, "match")],
                )
                function_annotations = _annotations()
            if fixture == "adapter-boundary":
                source_secondary_structure_track = AlignedResidueTrack(
                    source,
                    ("H", "E", None),
                )
            if fixture == "source-track-length-drift":
                source_track = AlignedResidueTrack(
                    source,
                    ("A", "G"),
                )
            elif fixture == "overlapping-residue-map":
                residue_map = ResidueMap(
                    source_layout=source,
                    target_layout=target,
                    mappings=[
                        (0, 0, "match"),
                        (0, 0, "match"),
                        (-1, 1, "insert"),
                        (2, 2, "match"),
                        (1, -1, "delete"),
                    ],
                )
            elif fixture == "unmapped-residue-map":
                residue_map = ResidueMap(
                    source_layout=source,
                    target_layout=target,
                    mappings=[
                        (0, 0, "match"),
                        (2, 2, "match"),
                        (1, -1, "delete"),
                    ],
                )
            elif fixture == "noncontiguous-chain-layout":
                source = ResidueLayout(
                    chain_id="A,B,A",
                    length=3,
                    residue_ids=["A:1", "B:1", "A:2"],
                )
                residue_map = ResidueMap(
                    source_layout=source,
                    target_layout=target,
                    mappings=[
                        (0, 0, "match"),
                        (-1, 1, "insert"),
                        (1, 2, "match"),
                        (2, -1, "delete"),
                    ],
                )
            elif fixture == "boundary-edit":
                target = ResidueLayout(
                    chain_id="A,B",
                    length=4,
                    residue_ids=["A:new", "A:1", "B:1", "B:new"],
                )
                residue_map = ResidueMap(
                    source_layout=source,
                    target_layout=target,
                    mappings=[
                        (-1, 0, "insert"),
                        (0, 1, "match"),
                        (2, 2, "match"),
                        (-1, 3, "insert"),
                        (1, -1, "delete"),
                    ],
                )
            elif fixture == "contradictory-residue-map":
                identical = ResidueLayout(
                    chain_id="A",
                    length=1,
                    residue_ids=["A:1"],
                )
                source = identical
                target = identical
                source_track = AlignedResidueTrack(
                    source,
                    ("A",),
                )
                source_secondary_structure_track = AlignedResidueTrack(
                    source,
                    ("H",),
                )
                visibility_track = AlignedResidueTrack(
                    source,
                    (True,),
                )
                residue_map = ResidueMap(
                    source_layout=source,
                    target_layout=target,
                    mappings=[
                        (-1, 0, "insert"),
                        (0, -1, "delete"),
                    ],
                )
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
            "source_layout": source,
            "target_layout": target,
            "source_sequence_track": source_track,
            "source_structure_track": source_structure_track,
            "source_visibility_track": visibility_track,
            "source_secondary_structure_track": (
                source_secondary_structure_track
            ),
            "target_secondary_structure_track": AlignedResidueTrack(
                target,
                tuple(
                    [None, "H", "-", None]
                    if fixture == "boundary-edit"
                    else (
                        ["H"]
                        if fixture == "contradictory-residue-map"
                        else (
                            list(source_secondary_structure_track.values)
                            if fixture in {
                                "3gb1-intent",
                                "insertion-identity-collision",
                            }
                            else ["H", None, "-"]
                        )
                    )
                ),
            ),
            "target_structure_track": AlignedResidueTrack(
                target,
                tuple(
                    None
                    for _ in range(target.length)
                ),
            ),
            "source_sasa_track": source_sasa_track,
            "residue_map": residue_map,
            "function_annotations": function_annotations,
            "protein_prompt": ProteinPrompt(
                target_layout=source,
                sequence_track=ResidueTrack(list(sequence_value), None),
                structure_track=ResidueTrack(
                    list(source_structure_track.values),
                    None,
                ),
                structure_visibility_track=ResidueTrack(
                    list(visibility_track.values),
                    None,
                ),
                secondary_structure_track=ResidueTrack(
                    list(source_secondary_structure_track.values),
                    None,
                ),
                sasa_track=ResidueTrack(
                    list(source_sasa_track.values),
                    None,
                ),
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
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.prompt_authoring_values.method",
            version=_VERSION,
            algorithm_identity={"name": "deterministic-fixture"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "identity-complete-layouts"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "identity"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.prompt_authoring_values.direct",
            version=_NODE_BINDING_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.prompt_authoring_values",
                _NODE_BINDING_VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.prompt_authoring_values.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.prompt_authoring_values/factory",
                    _VERSION,
                    {},
                ),
                build=_factory,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.prompt_authoring_values/availability",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.prompt_authoring_values/readiness",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "contract_test.prompt_authoring_values.direct",
                "source": "contract-test-fixture",
            },
        ),
    ),
)
