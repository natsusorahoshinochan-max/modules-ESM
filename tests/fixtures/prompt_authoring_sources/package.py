"""Independent typed values for prompt-authoring Contract Test Kit cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
)
from datatypes import (
    FunctionAnnotations,
    ProteinPrompt,
    ProteinSequence,
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
)
from modules.prompt_authoring.domain import AlignedResidueTrack


_VERSION = "2.0.0"


class _Source:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            inputs
            or set(node_parameters) != {"fixture"}
            or binding_parameters
        ):
            raise ValueError("prompt-authoring source accepts no values")
        with self._run_resources.engine_invocation(
            engine_identity=(
                "contract_test.prompt_authoring_values.method/2.0.0"
            ),
        ):
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
            function_annotations = FunctionAnnotations(
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
            if fixture == "annotation-overlap":
                function_annotations = FunctionAnnotations([
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
                function_annotations = FunctionAnnotations([
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
                function_annotations = FunctionAnnotations([
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
                function_annotations = FunctionAnnotations([
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
                        else ["H", None, "-"]
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
                        else "WFC"
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
        }


def _factory(**kwargs: object) -> object:
    return _Source(kwargs["run_resources"])


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
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
            version=_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.prompt_authoring_values",
                _VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.prompt_authoring_values.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=LazyImplementationFactory(
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
                check=lambda environment: True,
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
