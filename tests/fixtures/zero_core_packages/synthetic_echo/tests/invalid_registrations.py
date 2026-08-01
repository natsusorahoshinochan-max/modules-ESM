"""Independent malformed registrations used by negative CTK contracts."""

from __future__ import annotations

from dataclasses import replace

from core import (
    ArtifactPayload,
    BehaviorReference,
    OperationCall,
    OperationContext,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)

from ..package import MODULE_PACKAGE


class _IncompleteProvenanceImplementation:
    def __init__(self, *, run_resources, metric, method) -> None:
        self._run_resources = run_resources
        self._metric = metric
        self._method = method

    def execute(self, call: OperationCall):
        if call.inputs:
            raise ValueError("invalid fixture does not accept inputs")
        echoed = (
            call.node_parameters["message"]
            * call.binding_parameters["repeat_count"]
        )
        with self._run_resources.engine_invocation():
            pass
        candidate = Candidate(
            candidate_id="invalid-provenance-candidate",
            data=ProteinSequence(sequence="M"),
            parent_ids=[],
        )
        return {
            "text": echoed,
            "candidates": CandidateCollection(
                collection_id="invalid-provenance-candidates",
                item_type="protein.sequence",
                items=[candidate],
            ),
            "scores": ScoreCollection(
                collection_id="invalid-provenance-scores",
                entries=[
                    ScoreObservation(
                        candidate_id=candidate.candidate_id,
                        metric=self._metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=1.0,
                    )
                ],
            ),
            "artifact": ArtifactPayload(
                body=echoed.encode("utf-8"),
                media_type="text/plain",
                filename="result.txt",
            ),
        }


def _build_incomplete_provenance(context: OperationContext):
    metric = context.produced_observations[0].metric
    method_reference = {
        "contract_kind": context.method.contract_kind,
        "contract_id": context.method.contract_id,
        "contract_version": context.method.contract_version,
        "contract_digest": "sha256:" + ("0" * 64),
    }
    return _IncompleteProvenanceImplementation(
        run_resources=context.resources,
        metric=metric,
        method=ExactContractReference(**method_reference),
    )


_BINDING = MODULE_PACKAGE.bindings[0]


def _not_ready(environment) -> ReadinessResult:
    del environment
    return ReadinessResult(False)


FALSE_READINESS_PACKAGE = replace(
    MODULE_PACKAGE,
    bindings=(
        replace(
            _BINDING,
            readiness=ReadinessDeclaration(
                behavior=_BINDING.readiness.behavior,
                prerequisites=_BINDING.readiness.prerequisites,
                check=_not_ready,
            ),
        ),
    ),
)
INCOMPLETE_PROVENANCE_PACKAGE = replace(
    MODULE_PACKAGE,
    bindings=(
        replace(
            _BINDING,
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.incomplete_provenance/factory",
                    "2.1.0",
                    {},
                ),
                build=_build_incomplete_provenance,
            ),
        ),
    ),
)
