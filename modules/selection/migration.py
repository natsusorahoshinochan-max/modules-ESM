"""Offline one-time conversion of saved Selection configuration.

The current runtime never calls this converter or accepts global Selection rules.

Old Utility sort and weighted rank break ties by Candidate ID; current operations
preserve input ties. Old top-k also rejects oversized k. Old Pareto transforms
its inputs and orders its output by ID. Those saved configurations are not
equivalent to the current operations, regardless of a particular completed Run.
Diversity has no current replacement. The original node and global settings stay
readable inside a generic nonexecutable node state; no formulas are substituted.

Old filters resolve every selector before their postfix predicate. Converting
the tree alone cannot prove equivalent matching: the old matcher groups by
Candidate ID, whereas the current matcher uses the complete Candidate reference.
An extra observation with changed content under the same ID can therefore make
the old rule fail while the current rule succeeds. The default old out-of-scope
error policy also differs from current behavior. Saved filters remain blocked
unless that complete equivalence can be proved; this converter has no such
source guarantee. Manual selection already uses complete references and retains
input order, so its parameters and connections remain unchanged.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


_PRESERVATION_REASONS = {
    'selection.filter': 'Equivalent evaluation matching and out-of-scope behavior have not been established for the saved filter.',
    'selection.sort': 'Saved Utility sorting breaks score ties by Candidate ID; current raw sorting preserves input order.',
    'selection.top_k': 'Saved Utility top-k uses Candidate ID ties and rejects k above the input size; current raw top-k has different behavior.',
    'selection.weighted_rank': 'Saved weighting uses prior Utility definitions and Candidate ID ties; equivalent current weighting has not been established.',
    'selection.pareto': 'Saved Pareto uses Utility transforms and Candidate ID output order; current Pareto uses raw values and input order.',
    'selection.diversity': 'The saved diversity operation has been removed; its settings and connections are preserved for reading.',
}


def convert_selection_workflow(workflow: Mapping[str, Any]) -> dict[str, Any]:
    """Return an independent current Workflow, retaining saved scientific intent."""
    converted = deepcopy(dict(workflow))
    globals_ = {key: converted.get(key, [])
                for key in ('observation_selectors', 'selection_objectives')}
    globals_retained = False
    for node in converted['nodes']:
        kind = node['node_type_id']
        parameters = node['node_parameters']
        if 'preserved_configuration' in node:
            continue
        if kind in _PRESERVATION_REASONS and (kind == 'selection.diversity'
                or 'objective_id' in parameters or 'objective_ids' in parameters
                or 'selector_ids' in parameters or 'expression' in parameters):
            node['preserved_configuration'] = {
                'reason': _PRESERVATION_REASONS[kind],
                'settings': deepcopy(globals_),
                'project_input_parameters': [],
            }
            globals_retained = True
    if any(globals_.values()) and not globals_retained:
        existing_ids = {node['node_id'] for node in converted['nodes']}
        node_id = 'retained-selection-configuration'
        suffix = 2
        while node_id in existing_ids:
            node_id = f'retained-selection-configuration-{suffix}'
            suffix += 1
        converted['nodes'].append({
            'node_id': node_id,
            'node_type_id': 'selection.unavailable_configuration',
            'binding_id': 'selection.unavailable_configuration.direct',
            'node_parameters': {},
            'binding_parameters': {},
            'preserved_configuration': {
                'reason': 'Saved global Selection settings have no equivalent node-owned consumer; the original settings remain available for reading.',
                'settings': deepcopy(globals_),
                'project_input_parameters': [],
            },
        })
    converted.pop('observation_selectors', None)
    converted.pop('selection_objectives', None)
    return converted
