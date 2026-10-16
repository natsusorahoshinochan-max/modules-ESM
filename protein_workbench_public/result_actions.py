"""Generic dispatch of registered read-only actions on published typed values."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.catalog.model import FrozenCatalog
from core.catalog.result_actions import ResultActionError
from core.execution.ledger import V2RunError
from core.parameters.contract import ParameterValueAdmissionError, admit_values
from datatypes.candidate import CandidateDataReference


class ResultActionReader:
    def __init__(
        self, catalog: FrozenCatalog,
        read_value: Callable[..., tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]],
    ) -> None:
        self._catalog = catalog
        self._read_value = read_value

    def apply(
        self, project_id: str, run_id: str, node_id: str, output_port: str,
        value_index: int, action_id: str, parameters: dict[str, Any],
    ) -> dict[str, Any]:
        action = next((item for item in self._catalog.result_actions if item.action_id == action_id), None)
        if action is None:
            raise V2RunError("malformed_request", "Result action is not registered", details={"field_path": ["action_id"]})
        metadata, body, _ = self._read_value(project_id, run_id, node_id, output_port, value_index)
        if metadata["typed_value"]["port_type"]["contract_id"] != action.port_type_id:
            raise V2RunError("malformed_request", "Result action does not support this Port Type", details={"field_path": ["action_id"]})
        try:
            admitted = admit_values(action.parameters, parameters)
        except ParameterValueAdmissionError as error:
            raise V2RunError("malformed_request", str(error), details={"field_path": ["parameters"]}) from error
        try:
            return action.apply(body, admitted)
        except ResultActionError as error:
            raise V2RunError("malformed_request", str(error), details={"field_path": ["parameters"]}) from error
