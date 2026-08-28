"""Public-protocol helpers shared by task-shaped Workflow stress journeys."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.catalog.declarations import ModulePackageRegistration
from datatypes.candidate import CandidateCollection
from datatypes.sequence import ProteinSequence
from protein_workbench_public.bootstrap import module_registrations
from protein_workbench_public.workflow_codec import decode_workflow_document
from tests.fixtures.multi_objective_selection_sources.package import (
    MODULE_PACKAGE as SELECTION_SOURCE_PACKAGE,
)
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as PROMPT_SOURCE_PACKAGE,
)
from tests.fixtures.public_v2 import (
    retrieve_typed_output_canonical_bytes,
    wait_for_testclient_run_terminal,
)
from tests.fixtures.workflow_stress_sources.package import (
    MODULE_PACKAGE as WORKFLOW_STRESS_SOURCE_PACKAGE,
)


@dataclass(frozen=True, slots=True)
class StressRun:
    workflow_commit_id: str
    projection: dict[str, Any]
    events: tuple[dict[str, Any], ...]


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
    runs: Mapping[str, StressRun],
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


def configure_isolated_roots(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(root))


def commit_and_run(
    client: TestClient,
    project_id: str,
    workflow: dict[str, object],
    *,
    request_id: str,
    timeout_seconds: float = 5.0,
) -> StressRun:
    decode_workflow_document(workflow)
    committed = client.post(
        f"/api/v2/projects/{project_id}/workflow:commit",
        json={"workflow": workflow},
    )
    assert committed.status_code == 200, committed.json()
    return run_committed_workflow(
        client,
        project_id,
        committed.json()["workflow_commit_id"],
        request_id=request_id,
        timeout_seconds=timeout_seconds,
    )


def run_committed_workflow(
    client: TestClient,
    project_id: str,
    workflow_commit_id: str,
    *,
    request_id: str,
    timeout_seconds: float = 5.0,
) -> StressRun:
    started = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_commit_id": workflow_commit_id,
            "client_request_id": request_id,
        },
    )
    assert started.status_code == 202, started.json()
    run_id = started.json()["run_id"]
    projection = wait_for_testclient_run_terminal(
        client,
        project_id,
        run_id,
        timeout_seconds=timeout_seconds,
    )
    events: list[dict[str, Any]] = []
    with client.websocket_connect(
        f"/api/v2/projects/{project_id}/runs/{run_id}/events"
    ) as websocket:
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"]["type"] == "run_terminal":
                break
    return StressRun(workflow_commit_id, projection, tuple(events))


def _output(
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> dict[str, Any]:
    return next(
        output
        for output in projection["outputs"]
        if output["node_id"] == node_id
        and output["output_port"] == output_port
    )


def decode_one(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    output = _output(projection, node_id, output_port)
    assert output["value_count"] == 1
    port_type = catalog.require_port_type(
        output["port_type"]["contract_id"],
    )
    return port_type.decode(
        retrieve_typed_output_canonical_bytes(
            client,
            projection["project_id"],
            projection["run_id"],
            output,
            0,
        )
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
