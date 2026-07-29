"""Independent malformed registrations used by negative CTK contracts."""

from __future__ import annotations

from dataclasses import replace

from core import (
    BehaviorReference,
    LazyImplementationFactory,
    ReadinessDeclaration,
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

    def execute(self, *, inputs, node_parameters, binding_parameters):
        if inputs:
            raise ValueError("invalid fixture does not accept inputs")
        echoed = node_parameters["message"] * binding_parameters["repeat_count"]
        with self._run_resources.engine_invocation(
            engine_identity="contract_test.incomplete_provenance/2.0.0",
        ):
            pass
        candidate = Candidate(
            candidate_id="invalid-provenance-candidate",
            data=ProteinSequence(sequence="M"),
            parent_ids=[self._run_resources.node_id],
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
            "artifact": self._run_resources.write_artifact(
                "echo/result.txt",
                echoed.encode("utf-8"),
            ),
        }


def _build_incomplete_provenance(**kwargs):
    catalog = kwargs["frozen_catalog"]
    metric = catalog.require_contract(
        "metric",
        "contract_test.synthetic_identity",
        "2.0.0",
    )
    method = catalog.require_contract(
        "method",
        "contract_test.synthetic_echo.method",
        "2.0.0",
    )
    method_reference = method.reference()
    method_reference["contract_digest"] = "sha256:" + ("0" * 64)
    return _IncompleteProvenanceImplementation(
        run_resources=kwargs["run_resources"],
        metric=ExactContractReference(**metric.reference()),
        method=ExactContractReference(**method_reference),
    )


_BINDING = MODULE_PACKAGE.bindings[0]


def _not_ready(environment) -> bool:
    del environment
    return False


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
            factory=LazyImplementationFactory(
                behavior=BehaviorReference(
                    "contract_test.incomplete_provenance/factory",
                    "2.0.0",
                    {},
                ),
                build=_build_incomplete_provenance,
            ),
        ),
    ),
)
