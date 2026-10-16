"""Explicit controlled stress assembly and scenario-level reporting.

No consumer gets these tool replacements merely by importing run support.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
from typing import Any

from fastapi.testclient import TestClient
from core.catalog.declarations import ModulePackageRegistration
from datatypes.candidate import CandidateCollection
from datatypes.sequence import ProteinSequence
from protein_workbench_public.bootstrap import module_registrations
from tests.fixtures.multi_objective_selection_sources.package import (
    MODULE_PACKAGE as SELECTION_SOURCE_PACKAGE,
)
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as PROMPT_SOURCE_PACKAGE,
)
from tests.fixtures.workflow_stress_sources.package import (
    MODULE_PACKAGE as WORKFLOW_STRESS_SOURCE_PACKAGE,
)
from tests.support.public_journeys import PublicJourneyRun, decode_one


class ControlledStressProteinMPNN:
    """Deterministic single-chain ProteinMPNN provider boundary."""

    def __init__(self) -> None:
        self.parsed: list[str] = []
        self.requests: list[Any] = []

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        self.parsed.append(pdb_string)
        return [{
            "name": "stress-target",
            "seq": "AGSTW",
            "seq_chain_A": "AGSTW",
        }]

    @staticmethod
    def activate(model_name: str, backbone_noise: float) -> None:
        del model_name, backbone_noise

    def design(self, request: Any) -> list[ProteinSequence]:
        self.requests.append(request)
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        return [
            ProteinSequence(
                "AGST" + alphabet[(request.seed + index) % len(alphabet)]
            )
            for index in range(request.num_sequences)
        ]


def emit_stress_report(
    scenario: str,
    *,
    runs: Mapping[str, PublicJourneyRun],
    cardinalities: Mapping[str, int],
) -> None:
    """Emit one compact retained report after every scenario oracle passes."""
    print(json.dumps(
        {
            "workflow_stress_report": {
                "scenario": scenario,
                "oracle": "passed",
                "cardinalities": cardinalities,
                "runs": {
                    label: {
                        "node_count": len(
                            run.projection["node_dispositions"]
                        ),
                        "resolutions": dict(sorted(Counter(
                            item["resolution"]
                            for item in run.projection["node_dispositions"]
                        ).items())),
                        "engine_invocations": sum(
                            message["event"]["type"]
                            == "engine_invocation_started"
                            for message in run.events
                        ),
                    }
                    for label, run in runs.items()
                },
            }
        },
        sort_keys=True,
    ))


def stress_registrations() -> tuple[ModulePackageRegistration, ...]:
    """Return production contracts plus independent stress input sources."""
    return (
        *module_registrations(),
        SELECTION_SOURCE_PACKAGE,
        PROMPT_SOURCE_PACKAGE,
        WORKFLOW_STRESS_SOURCE_PACKAGE,
    )


def candidate_ids(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str = "candidates",
) -> tuple[str, ...]:
    collection = decode_one(
        client,
        catalog,
        projection,
        node_id,
        output_port,
    )
    assert type(collection) is CandidateCollection
    return tuple(candidate.candidate_id for candidate in collection.items)
