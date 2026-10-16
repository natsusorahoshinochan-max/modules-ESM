"""Ordinary operation adapter for Selection's public computation interface."""
from core.operation import OperationCall, OperationDiagnosticError
from datatypes.candidate import CandidateCollection
from .compute import SelectionError, select_candidates


class RawSelectionOperation:
    def __init__(self, operation: str) -> None:
        self.operation = operation

    def execute(self, call: OperationCall) -> dict[str, CandidateCollection]:
        candidates = call.inputs['candidates']
        scores = call.inputs.get('scores')
        relations = call.inputs.get('relations')
        try:
            return {'candidates': select_candidates(candidates.value, candidates.candidate_data,
                {slot: tuple(item.value for item in values) for slot, values in (scores.slots.items() if scores else ())},
                call.node_parameters, operation=self.operation,
                relation_inputs={slot: tuple(item.value for item in values) for slot, values in (relations.slots.items() if relations else ())})}
        except SelectionError as error:
            raise OperationDiagnosticError(str(error), diagnostic={'code': error.code}) from error
