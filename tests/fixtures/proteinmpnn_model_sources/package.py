"""Source-bound 3GB1 Candidate fixtures for real ProteinMPNN v2 gates."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
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
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PDB_PATH = (
    _PROJECT_ROOT / "examples" / "v2" / "structures" / "3GB1.pdb"
)
_PDB_SHA256 = (
    "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
)
_SEQUENCE = "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
_SEQUENCE_SHA256 = (
    "7e859d82171047700fd3e9632f7a47eab4a39baedc8c3316d2fc62d3ce2260bb"
)


class _StructureSource:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or node_parameters or binding_parameters:
            raise ValueError("3GB1 structure source accepts no values")
        pdb_string = _PDB_PATH.read_text()
        if hashlib.sha256(pdb_string.encode()).hexdigest() != _PDB_SHA256:
            raise RuntimeError("3GB1 structure fixture does not match its source")
        with self._resources.engine_invocation():
            candidate = Candidate(
                "source-bound-3gb1-structure",
                ProteinStructure(pdb_string),
                [],
                {"source_sha256": _PDB_SHA256},
            )
        return {
            "structure_candidates": CandidateCollection(
                "source-bound-3gb1-structures",
                "protein.structure",
                [candidate],
            )
        }


class _SequenceSource:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"structure_candidates"}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError("3GB1 sequence source requires one exact parent")
        parents = inputs["structure_candidates"].value
        if (
            type(parents) is not CandidateCollection
            or parents.item_type != "protein.structure"
            or len(parents.items) != 1
        ):
            raise ValueError("3GB1 sequence parent is ambiguous")
        if hashlib.sha256(_SEQUENCE.encode()).hexdigest() != _SEQUENCE_SHA256:
            raise RuntimeError("3GB1 sequence fixture does not match its source")
        parent = parents.items[0]
        with self._resources.engine_invocation():
            candidate = Candidate(
                "source-bound-3gb1-sequence",
                ProteinSequence(
                    _SEQUENCE,
                    [f"A:{index}" for index in range(1, 57)],
                ),
                [parent.candidate_id],
                {"source_sha256": _SEQUENCE_SHA256},
            )
        return {
            "sequence_candidates": CandidateCollection(
                "source-bound-3gb1-sequences",
                "protein.sequence",
                [candidate],
            )
        }


def _build(operation: str):
    def factory(context: OperationContext) -> object:
        implementation = (
            _StructureSource
            if operation == "structure"
            else _SequenceSource
        )
        return implementation(context.resources)

    return factory


def _method(operation: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"contract_test.proteinmpnn_3gb1_{operation}.method",
        algorithm_identity={"name": f"source-bound-3gb1-{operation}"},
        model_identity={"kind": "none"},
        featurization_identity={"kind": "exact-literal"},
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=(
            f"contract_test.proteinmpnn_3gb1_{operation}.direct"
        ),
        node_type=ContractIdentity(
            "node_type",
            f"contract_test.proteinmpnn_3gb1_{operation}"),
        method=ContractIdentity(
            "method",
            f"contract_test.proteinmpnn_3gb1_{operation}.method"),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"contract_test.proteinmpnn_3gb1_{operation}/factory",
                {},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"contract_test.proteinmpnn_3gb1_{operation}/availability",
                {},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.proteinmpnn_3gb1_{operation}/readiness",
                {},
            ),
            prerequisites={},
            check=lambda environment: ReadinessResult(True),
        ),
        deterministic=True,
        cacheable=True)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="contract_test.proteinmpnn_model_sources",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("structure.yaml"),
        DefinitionResource("sequence.yaml"),
    ),
    methods=tuple(_method(operation) for operation in ("structure", "sequence")),
    bindings=tuple(
        _binding(operation) for operation in ("structure", "sequence")
    ),
)
