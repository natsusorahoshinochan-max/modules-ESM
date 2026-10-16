"""Independent immutable snapshots of explicitly adopted published values."""
from dataclasses import dataclass
import json
from typing import Any, TypedDict, cast

from core.operation import OperationCall, OperationResources


class AdoptedCandidateReference(TypedDict):
    candidate_id: str
    data_type_id: str
    content_digest: str


class AdoptedSource(TypedDict):
    source_project_id: str
    source_run_id: str
    node_id: str
    output_port: str
    value_index: int


class AdoptedSnapshot(TypedDict):
    port_type_id: str
    canonical_value: str
    content_digest: str
    candidate_data: list[AdoptedCandidateReference]
    source: AdoptedSource
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RestoredOutput:
    """Canonical output read from this operation's declared Project Input."""
    snapshot: AdoptedSnapshot


def read_adopted_snapshot(payload: bytes) -> AdoptedSnapshot:
    return cast(AdoptedSnapshot, json.loads(payload))


class AdoptedInputOperation:
    def __init__(self, resources: OperationResources) -> None:
        self.resources = resources

    def execute(self, call: OperationCall) -> dict[str, RestoredOutput]:
        _, payload = self.resources.read_project_input(call.node_parameters['project_input_ref'])
        return {'value': RestoredOutput(read_adopted_snapshot(payload))}
