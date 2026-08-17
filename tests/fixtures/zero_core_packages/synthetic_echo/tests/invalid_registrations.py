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
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
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
        if set(call.inputs) != {"candidate_input"}:
            raise ValueError("invalid fixture requires Candidate input")
        echoed = (
            call.node_parameters["message"]
            * call.binding_parameters["repeat_count"]
        )
        with self._run_resources.engine_invocation():
            pass
        candidates = call.inputs["candidate_input"]
        if type(candidates) is not CandidateCollection:
            raise ValueError(
                "invalid fixture candidate_input must be a Candidate collection"
            )
        outputs = {
            "text": echoed,
            "candidates": candidates,
            "artifact": ArtifactPayload(
                body=echoed.encode("utf-8"),
                media_type="text/plain",
                filename="result.txt",
            ),
        }
        references = call.input_content_digests[
            "candidate_input"
        ].candidate_data
        outputs["scores"] = ScoreCollection(
            collection_id="invalid-provenance-scores",
            entries=[
                ScoreObservation(
                    subject=reference,
                    metric=self._metric,
                    method=self._method,
                    context=IntrinsicObservationContext(),
                    value=1.0,
                )
                for reference in references
            ],
        )
        return outputs


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


_BINDINGS = MODULE_PACKAGE.bindings
_SCORER_BINDING = next(
    binding
    for binding in _BINDINGS
    if binding.binding_id == "contract_test.synthetic_echo.direct"
)


def _not_ready(environment) -> ReadinessResult:
    del environment
    return ReadinessResult(False)


FALSE_READINESS_PACKAGE = replace(
    MODULE_PACKAGE,
    bindings=tuple(
        replace(
            binding,
            execution_route="adapter",
            adapter_behavior=BehaviorReference(
                f"{binding.binding_id}/fixture-adapter",
                binding.version,
                {"provider_contract": "contract-test"},
            ),
            readiness=ReadinessDeclaration(
                behavior=binding.readiness.behavior,
                prerequisites=binding.readiness.prerequisites,
                check=_not_ready,
            ),
        )
        for binding in _BINDINGS
    ),
)
INCOMPLETE_PROVENANCE_PACKAGE = replace(
    MODULE_PACKAGE,
    bindings=tuple(
        replace(
            binding,
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.incomplete_provenance/factory",
                    _SCORER_BINDING.version,
                    {},
                ),
                build=_build_incomplete_provenance,
            ),
        )
        if binding is _SCORER_BINDING
        else binding
        for binding in _BINDINGS
    ),
)
