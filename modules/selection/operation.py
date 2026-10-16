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


class ManualSelectionOperation:
    """Keep checked exact references in their current Candidate input order."""

    def execute(self, call: OperationCall) -> dict[str, CandidateCollection]:
        candidates = call.inputs['candidates'].value
        requested = {(item['candidate_id'], item['data_type_id'], item['content_digest'])
                     for item in call.node_parameters['selected_candidates']}
        present = {(item.candidate_id, item.data_type_id, item.content_digest)
                   for item in call.inputs['candidates'].candidate_data}
        missing = requested - present
        if missing:
            candidate_id, data_type_id, content_digest = min(missing)
            raise OperationDiagnosticError(
                f'Manual selection references missing from current input: {len(missing)}; first Candidate: {candidate_id}',
                diagnostic={'code': 'missing_candidate_reference', 'missing_candidate_count': len(missing),
                    'first_missing_candidate_reference': {'candidate_id': candidate_id,
                        'data_type_id': data_type_id, 'content_digest': content_digest}})
        selected_ids = {item[0] for item in requested}
        return {'candidates': CandidateCollection('selection-manual', candidates.item_type,
            tuple(item for item in candidates if item.candidate_id in selected_ids))}
