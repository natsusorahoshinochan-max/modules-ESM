"""Generic dispatch of registered read-only actions on published typed values."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.catalog.model import FrozenCatalog
from core.catalog.result_actions import ResultActionError, ResultActionValue
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
        self, project_id: str, run_id: str, inputs: dict[str, list[dict[str, Any]]],
        action_id: str, parameters: dict[str, Any],
    ) -> dict[str, Any]:
        action = next((item for item in self._catalog.result_actions if item.action_id == action_id), None)
        if action is None:
            raise V2RunError("malformed_request", "Result action is not registered", details={"field_path": ["action_id"]})
        declarations = {input.name: input for input in action.inputs}
        if set(inputs) - declarations.keys():
            raise V2RunError('malformed_request', 'Result action received an undeclared input', details={'field_path': ['inputs']})
        values = {}
        for name, declaration in declarations.items():
            locations = inputs.get(name, [])
            if (declaration.required and not locations) or (declaration.multiplicity == 'one' and len(locations) > 1):
                raise V2RunError('malformed_request', f'Result action input {name!r} has invalid cardinality', details={'field_path': ['inputs', name]})
            slots: dict[str, list[ResultActionValue]] = {}
            for location in locations:
                metadata, body, references = self._read_value(project_id, run_id,
                    location['node_id'], location['output_port'], location['value_index'])
                if metadata['typed_value']['port_type']['contract_id'] != declaration.port_type_id:
                    raise V2RunError('malformed_request', f'Result action input {name!r} does not support this Port Type', details={'field_path': ['inputs', name]})
                slots.setdefault(location['slot'], []).append(ResultActionValue(body, references))
            values[name] = {slot: tuple(items) for slot, items in slots.items()}
        try:
            admitted = admit_values(action.parameters, parameters)
        except ParameterValueAdmissionError as error:
            raise V2RunError("malformed_request", str(error), details={"field_path": ["parameters"]}) from error
        try:
            return action.apply(values, admitted)
        except ResultActionError as error:
            raise V2RunError("malformed_request", str(error), details={"field_path": ["parameters"]}) from error
