"""Provider-free implementation for the source-local synthetic package."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Mapping

from core import ArtifactPayload
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)


class SyntheticEchoImplementation:
    """Emit every typed value family exercised by the Contract Test Kit."""

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

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs:
            raise ValueError("synthetic echo does not accept inputs")
        message = node_parameters["message"]
        repeat_count = binding_parameters["repeat_count"]
        echoed = message * repeat_count
        with self._run_resources.engine_invocation(
            engine_identity="contract_test.synthetic_echo.method/2.0.0",
        ):
            marker_value = self._environment.get("block_marker")
            if isinstance(marker_value, str):
                marker = Path(marker_value)
                if marker.exists():
                    marker.with_suffix(".started").write_text(
                        "started",
                        encoding="utf-8",
                    )
                    while marker.exists():
                        time.sleep(0.05)
        candidate = Candidate(
            candidate_id="synthetic-candidate",
            data=ProteinSequence(sequence="M"),
            parent_ids=[self._run_resources.node_id],
            metadata={"fixture": "zero-core-extension"},
        )
        candidates = CandidateCollection(
            collection_id="synthetic-candidates",
            item_type="protein.sequence",
            items=[candidate],
        )
        scores = ScoreCollection(
            collection_id="synthetic-scores",
            entries=[
                ScoreObservation(
                    candidate_id=candidate.candidate_id,
                    metric=self._metric,
                    method=self._method,
                    context=IntrinsicObservationContext(),
                    value=1.0,
                )
            ],
        )
        artifact = ArtifactPayload(
            body=echoed.encode("utf-8"),
            media_type="text/plain",
            filename="result.txt",
        )
        return {
            "text": echoed,
            "candidates": candidates,
            "scores": scores,
            "artifact": artifact,
        }
