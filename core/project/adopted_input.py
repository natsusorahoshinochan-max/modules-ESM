"""Independent immutable snapshots of explicitly adopted published values."""
from dataclasses import dataclass
import json
from typing import Any

from core.operation import OperationCall, OperationResources


@dataclass(frozen=True, slots=True)
class RestoredOutput:
    """Canonical output read from this operation's declared Project Input."""
    snapshot: dict[str, Any]


class AdoptedInputOperation:
    def __init__(self, resources: OperationResources) -> None:
        self.resources = resources

    def execute(self, call: OperationCall) -> dict[str, RestoredOutput]:
        _, payload = self.resources.read_project_input(call.node_parameters['project_input_ref'])
        return {'value': RestoredOutput(json.loads(payload))}
