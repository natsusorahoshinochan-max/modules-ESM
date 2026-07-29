"""Independent sequence-Candidate source for folding acceptance."""

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
from datatypes import Candidate, CandidateCollection, ProteinSequence


_VERSION = "2.0.0"


class _SequenceSource:
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
        with self._run_resources.engine_invocation(
            engine_identity="contract_test.folding_sequence_source/2.0.0",
        ):
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


def _build(**kwargs: object) -> object:
    return _SequenceSource(kwargs["run_resources"])


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="contract_test.folding_sources",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.folding_sequence_source.method",
            version=_VERSION,
            algorithm_identity={"name": "independent-literal-source"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "identity"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.folding_sequence_source.direct",
            version=_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.folding_sequence_source",
                _VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.folding_sequence_source.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=LazyImplementationFactory(
                behavior=BehaviorReference(
                    "contract_test.folding_sequence_source/factory",
                    _VERSION,
                    {},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.folding_sequence_source/availability",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.folding_sequence_source/readiness",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: True,
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "contract_test.folding_sequence_source.direct",
                "source": "contract-test-fixture",
            },
        ),
    ),
)
