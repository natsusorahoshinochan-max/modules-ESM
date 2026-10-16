"""Module-owned weighted ranking using the metric owner's scoring declarations."""
from collections.abc import Mapping, Sequence
from dataclasses import replace
import math
from typing import Any

from core.catalog.declarations import ParameterDependencies, UtilityTransformDefinition
from core.operation import OperationCall
from core.parameters.contract import admit_values
from datatypes.candidate import CandidateCollection, CandidateDataReference
from datatypes.exact_reference import ExactContractReference as Ref
from datatypes.observation import ScoreCollection, CandidateRelation

from .compute import SelectionError, resolve_observations


def active_objectives(parameters: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Discard inactive terms before resolving observations or definitions."""
    objectives = parameters['objectives']
    if any(type(item['weight']) not in (int, float) or not math.isfinite(item['weight']) or item['weight'] < 0
           for item in objectives):
        raise SelectionError('invalid_weight', 'Relative weights must be finite and nonnegative')
    active = tuple(item for item in objectives if item['weight'] > 0)
    if not active:
        raise SelectionError('invalid_weight', 'Relative weights must have a positive total')
    return active


def weighted_dependencies(node_parameters: Mapping[str, Any], binding_parameters: Mapping[str, Any]) -> ParameterDependencies:
    roots = []
    slots = []
    for objective in active_objectives(node_parameters):
        selection = objective['selection']
        roots.extend((Ref('metric', selection['metric_id']), Ref('method', selection['method_id']),
                      Ref('utility_transform', objective['transform_id'])))
        slots.append(('scores', selection['score_input']))
        if 'relation_input' in selection:
            slots.append(('relations', selection['relation_input']))
    return ParameterDependencies(tuple(roots), tuple(slots))


def weighted_scores(columns: Sequence[Sequence[float]], weights: Sequence[float]) -> tuple[float, ...]:
    """Compute the normalized weighted mean without overflowing finite weights."""
    largest = max(weights)
    relative = tuple(weight / largest for weight in weights)
    total = math.fsum(relative)
    return tuple(math.fsum(value * weight for value, weight in zip(values, relative, strict=True)) / total
                 for values in zip(*columns, strict=True))


def rank_weighted_candidates(
    candidates: CandidateCollection,
    candidate_references: Sequence[CandidateDataReference],
    score_inputs: Mapping[str, tuple[ScoreCollection, ...]],
    parameters: Mapping[str, Any],
    definitions: Mapping[tuple[str, str], Any],
    relation_inputs: Mapping[str, tuple[CandidateRelation, ...]] | None = None,
) -> CandidateCollection:
    """Use the exact frozen scoring implementations while preserving raw inputs."""
    active = active_objectives(parameters)
    columns = []
    for objective in active:
        selection = objective['selection']
        transform: UtilityTransformDefinition = definitions[('utility_transform', objective['transform_id'])]
        compatible = transform.compatible_input_contract
        if (compatible['metric'].contract_id != selection['metric_id']
            or compatible['method'].contract_id != selection['method_id']
            or compatible['context_profile'] != selection['context']):
            raise SelectionError('inapplicable_scoring', 'Selected scoring choice is not applicable to the exact Metric, Method and Context')
        defaults = admit_values(transform.parameter_contract, {})
        observations = resolve_observations(selection, candidate_references, score_inputs, relation_inputs)
        values = tuple(transform.transform(observation.value, defaults) for observation in observations)
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise SelectionError('invalid_scoring', 'Module scoring choice must return finite values in [0, 1]')
        columns.append(values)
    scores = dict(zip((reference.candidate_id for reference in candidate_references),
                      weighted_scores(columns, [item['weight'] for item in active]), strict=True))
    return replace(candidates, items=tuple(sorted(candidates, key=lambda candidate: scores[candidate.candidate_id], reverse=True)))


class WeightedSelectionOperation:
    def __init__(self, definitions: Mapping[tuple[str, str], Any]) -> None:
        self.definitions = definitions

    def execute(self, call: OperationCall) -> dict[str, CandidateCollection]:
        candidates = call.inputs['candidates']
        scores = call.inputs.get('scores')
        relations = call.inputs.get('relations')
        return {'candidates': rank_weighted_candidates(candidates.value, candidates.candidate_data,
            {slot: tuple(item.value for item in values) for slot, values in (scores.slots.items() if scores else ())},
            call.node_parameters, self.definitions,
            {slot: tuple(item.value for item in values) for slot, values in (relations.slots.items() if relations else ())})}
