"""Independent single-chain parent source for Workflow stress tests."""

from __future__ import annotations

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
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference
from core.operation import OperationCall, OperationContext, ReadinessResult
from datatypes.candidate import Candidate, CandidateCollection
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from tests.fixtures.canonical_3gb1_v2 import pdb_for_sequence


_SEQUENCE = "AGSTW"


class _StructureParents:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.inputs or call.node_parameters or call.binding_parameters:
            raise ValueError("Workflow stress structure source accepts no inputs")
        with self._resources.engine_invocation():
            parents = tuple(
                Candidate(
                    f"stress-structure-parent-{index}",
                    ProteinStructure(
                        pdb_for_sequence(
                            _SEQUENCE,
                            bend=index * 0.15,
                            z_offset=index * 0.01,
                        )
                    ),
                    (),
                    {"fixture_parent_index": index},
                )
                for index in range(2)
            )
        return {
            "structure_candidates": CandidateCollection(
                "stress-structure-parents",
                "protein.structure",
                parents,
            ),
            "sequence": ProteinSequence(
                _SEQUENCE,
                tuple(f"A:{index}" for index in range(1, 6)),
            ),
        }


def _factory(context: OperationContext) -> _StructureParents:
    return _StructureParents(context.resources)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="contract_test.workflow_stress_sources",
    package_module=__package__,
    node_definitions=(DefinitionResource("structure_source.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.workflow_stress_structure_source.method",
            algorithm_identity={"name": "two-independent-literal-parents"},
            model_identity={"kind": "none"},
            featurization_identity={"kind": "single-chain-pdb"},
            scale_contract={"parent_count": 2, "residue_count": 5},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.workflow_stress_structure_source.direct",
            node_type=ContractIdentity(
                "node_type",
                "contract_test.workflow_stress_structure_source"),
            method=ContractIdentity(
                "method",
                "contract_test.workflow_stress_structure_source.method"),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.workflow_stress_structure_source/factory",
                    {},
                ),
                build=_factory,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.workflow_stress_structure_source/availability",
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.workflow_stress_structure_source/readiness",
                    {},
                ),
                prerequisites={},
                check=lambda _environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True),
    ),
)
