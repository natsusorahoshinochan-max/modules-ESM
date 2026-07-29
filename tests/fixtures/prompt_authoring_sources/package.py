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
from datatypes import ResidueLayout, ResidueMap
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
            "residue_map": residue_map,
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
