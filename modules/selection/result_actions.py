"""Read-only Selection adapter over declared immutable published inputs."""
from collections.abc import Mapping
from importlib import resources
from typing import Any

import yaml

from core.catalog.builtins import builtin_frozen_catalog
from core.catalog.result_actions import ResultActionDefinition, ResultActionError, ResultActionInput, ResultActionInputs
from core.parameters.contract import admit_declarations
from datatypes.i_json import thaw_i_json
from .compute import SelectionError, select_candidates


def view_candidates(inputs: ResultActionInputs, parameters: Mapping[str, Any]) -> dict[str, Any]:
    candidate_value = next(iter(inputs['candidates'].values()))[0]
    contracts = builtin_frozen_catalog()
    candidates = contracts.require_port_type('candidate.collection').restore(candidate_value.body)
    references = candidate_value.candidate_references
    scores = {slot: tuple(contracts.require_port_type('score.collection').restore(value.body) for value in values)
              for slot, values in inputs['scores'].items()}
    relations = {slot: tuple(contracts.require_port_type('candidate.relation').restore(value.body) for value in values)
                 for slot, values in inputs['relations'].items()}
    try:
        selected = candidates
        if 'condition' in parameters:
            selected = select_candidates(selected, references, scores, parameters, operation='filter', relation_inputs=relations)
        if 'sort' in parameters:
            selected_ids = {candidate.candidate_id for candidate in selected}
            selected_references = tuple(reference for reference in references if reference.candidate_id in selected_ids)
            selected = select_candidates(selected, selected_references, scores, parameters['sort'], operation='sort', relation_inputs=relations)
    except SelectionError as error:
        raise ResultActionError(str(error)) from error
    positions = {candidate.candidate_id: index for index, candidate in enumerate(candidates)}
    return {'candidate_indices': [positions[candidate.candidate_id] for candidate in selected]}


def _parameters():
    """Use exactly the node-owned parameter grammar at both public adapters."""
    def declarations(operation):
        return yaml.safe_load(resources.files(__package__).joinpath(f'definitions/{operation}.yaml').read_text())['node_parameters']
    condition = declarations('filter')['condition']
    condition['required'] = False
    sorting = declarations('sort')
    return admit_declarations({
        'condition': condition,
        'sort': {'parameter_scope': 'scientific', 'scientific_meaning': 'Temporary raw-value ordering after filtering.',
                 'required': False, 'value_contract': {'type': 'object', 'additionalProperties': False,
                    'required': ['selection', 'direction'], 'properties': {
                        name: {**thaw_i_json(value['value_contract']), 'field_scope': 'scientific',
                               'scientific_meaning': value['scientific_meaning']}
                        for name, value in sorting.items()}}},
    }, path='selection.view')


VIEW_CANDIDATES_ACTION = ResultActionDefinition(
    action_id='selection.view',
    inputs=(ResultActionInput('candidates', 'candidate.collection'),
            ResultActionInput('scores', 'score.collection', 'many', False),
            ResultActionInput('relations', 'candidate.relation', 'many', False)),
    parameters=_parameters(), apply=view_candidates,
)
