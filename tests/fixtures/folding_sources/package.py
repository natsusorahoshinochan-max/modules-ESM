"""Independent sequence-Candidate source for folding acceptance."""

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


class _SequenceSource:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            inputs
            or set(node_parameters) != {"sequence"}
            or binding_parameters
        ):
            raise ValueError("folding source accepts only one exact sequence")
        sequence = node_parameters["sequence"]
        if (
            not isinstance(sequence, str)
            or not sequence
            or any(
                symbol not in "ACDEFGHIKLMNPQRSTVWY"
                for symbol in sequence
            )
        ):
            raise ValueError("folding source sequence is invalid")
        with self._run_resources.engine_invocation():
            candidate = Candidate(
                "fixture-sequence",
                ProteinSequence(
                    sequence,
                    [
                        f"A:{index}"
                        for index in range(1, len(sequence) + 1)
                    ],
                ),
                [],
                {"source": "independent-literal"},
            )
        return {
            "sequence_candidates": CandidateCollection(
                "fixture-sequences",
                "protein.sequence",
                [candidate],
            )
        }


class _SequenceBatchSource:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            inputs
            or set(node_parameters) != {"sequences"}
            or binding_parameters
        ):
            raise ValueError(
                "folding batch source accepts only exact sequences"
            )
        sequences = node_parameters["sequences"]
        if (
            not isinstance(sequences, (list, tuple))
            or not sequences
            or any(
                not isinstance(sequence, str)
                or not sequence
                or any(
                    symbol not in "ACDEFGHIKLMNPQRSTVWY"
                    for symbol in sequence
                )
                for sequence in sequences
            )
        ):
            raise ValueError("folding batch source sequences are invalid")
        with self._run_resources.engine_invocation():
            candidates = [
                Candidate(
                    f"fixture-sequence-{index}",
                    ProteinSequence(
                        sequence,
                        [
                            f"A:{residue_index}"
                            for residue_index in range(
                                1,
                                len(sequence) + 1,
                            )
                        ],
                    ),
                    [],
                    {
                        "source": "independent-literal",
                        "input_order": index,
                    },
                )
                for index, sequence in enumerate(sequences)
            ]
        return {
            "sequence_candidates": CandidateCollection(
                "fixture-sequence-batch",
                "protein.sequence",
                candidates,
            )
        }


class _StructureSource:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            inputs
            or set(node_parameters) != {"pdb_string"}
            or binding_parameters
        ):
            raise ValueError(
                "folding structure source accepts only one exact PDB string"
            )
        pdb_string = node_parameters["pdb_string"]
        if not isinstance(pdb_string, str) or "ATOM" not in pdb_string:
            raise ValueError("folding structure source PDB is invalid")
        with self._run_resources.engine_invocation():
            candidate = Candidate(
                "fixture-structure",
                ProteinStructure(
                    pdb_string=pdb_string,
                ),
                [],
                {"source": "independent-literal"},
            )
        return {
            "structure_candidates": CandidateCollection(
                "fixture-structures",
                "protein.structure",
                [candidate],
            )
        }


def _build(kind: str):
    def factory(context: OperationContext) -> object:
        if kind == "sequence":
            return _SequenceSource(context.resources)
        if kind == "sequence_batch":
            return _SequenceBatchSource(context.resources)
        return _StructureSource(context.resources)

    return factory


def _method(kind: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"contract_test.folding_{kind}_source.method",
        algorithm_identity={"name": "independent-literal-source"},
        model_identity={"kind": "none"},
        featurization_identity={"kind": "literal"},
        scale_contract={"kind": "identity"},
    )


def _binding(kind: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"contract_test.folding_{kind}_source.direct",
        node_type=ContractIdentity(
            "node_type",
            f"contract_test.folding_{kind}_source"),
        method=ContractIdentity(
            "method",
            f"contract_test.folding_{kind}_source.method"),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"contract_test.folding_{kind}_source/factory",
                {},
            ),
            build=_build(kind),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"contract_test.folding_{kind}_source/availability",
                {},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.folding_{kind}_source/readiness",
                {},
            ),
            prerequisites={},
            check=lambda environment: ReadinessResult(True),
        ),
        deterministic=True,
        cacheable=True)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="contract_test.folding_sources",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definition.yaml"),
        DefinitionResource("batch_definition.yaml"),
        DefinitionResource("structure_definition.yaml"),
    ),
    methods=tuple(
        _method(kind) for kind in ("sequence", "sequence_batch", "structure")
    ),
    bindings=tuple(
        _binding(kind) for kind in ("sequence", "sequence_batch", "structure")
    ),
)
