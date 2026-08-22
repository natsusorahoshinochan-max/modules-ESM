"""Provider-free implementation for the source-local synthetic package."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Mapping

from core.operation import (
    ArtifactPayload,
    OperationCall,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence


def _execute_echo(
    call: OperationCall,
    *,
    run_resources: Any,
    environment: Mapping[str, Any],
) -> tuple[str, ArtifactPayload]:
    message = call.node_parameters["message"]
    repeat_count = call.binding_parameters["repeat_count"]
    echoed = message * repeat_count
    with run_resources.engine_invocation():
        marker_value = environment.get("block_marker")
        if isinstance(marker_value, str):
            marker = Path(marker_value)
            if marker.exists():
                marker.with_suffix(".started").write_text(
                    "started",
                    encoding="utf-8",
                )
                while marker.exists():
                    time.sleep(0.05)
    return echoed, ArtifactPayload(
        body=echoed.encode("utf-8"),
        media_type="text/plain",
        filename="result.txt",
    )


class SyntheticCandidateSourceImplementation:
    """Emit one deterministic Candidate without accepting scientific inputs."""

    def __init__(
        self,
        *,
        run_resources: Any,
        environment: Mapping[str, Any],
    ) -> None:
        self._run_resources = run_resources
        self._environment = environment

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.inputs:
            raise ValueError("synthetic Candidate source does not accept inputs")
        echoed, artifact = _execute_echo(
            call,
            run_resources=self._run_resources,
            environment=self._environment,
        )
        candidate = Candidate(
            candidate_id="synthetic-candidate",
            data=ProteinSequence(sequence="M"),
            parent_ids=[],
            metadata={"fixture": "zero-core-extension"},
        )
        return {
            "text": echoed,
            "candidates": CandidateCollection(
                collection_id="synthetic-candidates",
                item_type="protein.sequence",
                items=[candidate],
            ),
            "artifact": artifact,
        }


class SyntheticEchoScorerImplementation:
    """Score and echo exact admitted Candidate inputs."""

    def __init__(
        self,
        *,
        run_resources: Any,
        environment: Mapping[str, Any],
        metric: ExactContractReference,
        method: ExactContractReference,
    ) -> None:
        self._run_resources = run_resources
        self._environment = environment
        self._metric = metric
        self._method = method

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if set(call.inputs) != {"candidate_input"}:
            raise ValueError("synthetic echo scorer requires Candidate input")
        candidates = call.inputs["candidate_input"].value
        if type(candidates) is not CandidateCollection:
            raise ValueError(
                "synthetic echo candidate_input must be a Candidate collection"
            )
        echoed, artifact = _execute_echo(
            call,
            run_resources=self._run_resources,
            environment=self._environment,
        )
        admitted = call.inputs["candidate_input"]
        references = admitted.candidate_data
        return {
            "text": echoed,
            "candidates": candidates,
            "scores": ScoreCollection(
                collection_id="synthetic-scores",
                entries=[
                    ScoreObservation(
                        subject=reference,
                        metric=self._metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        source_partition="default",
                        value=1.0,
                    )
                    for reference in references
                ],
            ),
            "artifact": artifact,
        }
