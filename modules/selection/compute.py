"""Selection's public calculation interface, shared by nodes and result viewing."""
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, replace
import math
from typing import Any

from datatypes.candidate import CandidateCollection, CandidateDataReference
from datatypes.i_json import i_json_values_equal, freeze_i_json
from datatypes.observation import (ScoreCollection, ScoreObservation,
    observation_context_profile, observation_context_profile_descriptor, PairwiseObservationContext,
    IntrinsicObservationContext, CalibrationObservationContext, CandidateRelation)


class SelectionError(ValueError):
    """An evaluation is missing, ambiguous or cannot satisfy the chosen rule."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _published_context(
    context: IntrinsicObservationContext | CalibrationObservationContext | PairwiseObservationContext,
) -> dict[str, Any]:
    values = asdict(context)
    return {field.name: values[field.name] for field in fields(context)
            if not (field.metadata.get('wire_optional') and values[field.name] is None)}


def resolve_observations(
    selection: Mapping[str, Any],
    candidate_references: Sequence[CandidateDataReference],
    score_inputs: Mapping[str, tuple[ScoreCollection, ...]],
    relation_inputs: Mapping[str, tuple[CandidateRelation, ...]] | None = None,
) -> tuple[ScoreObservation, ...]:
    """Resolve exactly one chosen existing observation for every input subject."""
    if not candidate_references:
        return ()
    slot = selection['score_input']
    if slot not in score_inputs and candidate_references:
        raise SelectionError('missing_score', f'Score input {slot!r} is disconnected')
    observations = [entry for collection in score_inputs.get(slot, ()) for entry in collection]
    relation_entries = None
    if 'relation_input' in selection:
        slot = selection['relation_input']
        if not relation_inputs or slot not in relation_inputs:
            raise SelectionError('missing_relation', f'Relation input {slot!r} is disconnected')
        relation_entries = [entry for relation in relation_inputs[slot] for entry in relation.entries]
    result = []
    for reference in candidate_references:
        matches = [entry for entry in observations if entry.subject == reference
                   and entry.metric.contract_id == selection['metric_id']
                   and entry.method.contract_id == selection['method_id']
                   and entry.source_partition == selection['source_partition']
                   and observation_context_profile_descriptor(observation_context_profile(entry.context)) == selection['context']]
        if relation_entries is not None:
            references = [entry.reference for entry in relation_entries if entry.subject == reference]
            if len(references) != 1:
                raise SelectionError('ambiguous_relation', f'Candidate {reference.candidate_id} needs exactly one explicit reference')
            matches = [entry for entry in matches if isinstance(entry.context, PairwiseObservationContext)
                       and entry.context.reference.candidate == references[0]]
        if 'reference' in selection:
            expected_reference = CandidateDataReference(**selection['reference'])
            matches = [entry for entry in matches if isinstance(entry.context, PairwiseObservationContext)
                       and entry.context.reference.candidate == expected_reference]
        if 'exact_contexts' in selection:
            choices = [choice for choice in selection['exact_contexts']
                       if CandidateDataReference(**choice['subject']) == reference]
            if len(choices) != 1:
                raise SelectionError('ambiguous_context', f'Candidate {reference.candidate_id} needs exactly one saved context choice')
            choice = choices[0]
            matches = [entry for entry in matches
                       if i_json_values_equal(freeze_i_json(_published_context(entry.context)), freeze_i_json(choice['context']))
                       and ('residue_axis' not in choice or i_json_values_equal(
                           freeze_i_json(asdict(entry.residue_axis)) if entry.residue_axis is not None else None, freeze_i_json(choice['residue_axis'])))]
        if len(matches) != 1:
            raise SelectionError('missing_score' if not matches else 'ambiguous_score',
                                 f'Candidate {reference.candidate_id} needs exactly one selected evaluation; found {len(matches)}')
        if matches[0].value is None:
            raise SelectionError('missing_score', f'Candidate {reference.candidate_id} has a missing selected measurement')
        if type(matches[0].value) not in (int, float) or not math.isfinite(matches[0].value):
            raise SelectionError('invalid_score', f'Candidate {reference.candidate_id} requires a finite scalar measurement')
        result.append(matches[0])
    return tuple(result)


def select_candidates(candidates: CandidateCollection,
                      candidate_references: Sequence[CandidateDataReference],
                      score_inputs: Mapping[str, tuple[ScoreCollection, ...]],
                      parameters: Mapping[str, Any], *, operation: str,
                      relation_inputs: Mapping[str, tuple[CandidateRelation, ...]] | None = None) -> CandidateCollection:
    """Sort or select original candidates using raw values and stable input ties."""
    if operation == 'pareto':
        objectives = parameters['objectives']
        columns = tuple({reference.candidate_id: score.value for reference, score in zip(
            candidate_references, resolve_observations(objective['selection'], candidate_references,
                score_inputs, relation_inputs), strict=True)} for objective in objectives)
        def dominates(other: str, candidate: str) -> bool:
            comparisons = tuple(
                (column[other] <= column[candidate], column[other] < column[candidate])
                if objective['direction'] == 'ascending' else
                (column[other] >= column[candidate], column[other] > column[candidate])
                for objective, column in zip(objectives, columns, strict=True))
            return all(no_worse for no_worse, _ in comparisons) and any(better for _, better in comparisons)
        return replace(candidates, items=tuple(candidate for candidate in candidates
            if not any(dominates(other.candidate_id, candidate.candidate_id)
                for other in candidates if other.candidate_id != candidate.candidate_id)))
    scores = resolve_observations(parameters['selection'], candidate_references, score_inputs, relation_inputs)
    values = {ref.candidate_id: score.value for ref, score in zip(candidate_references, scores, strict=True)}
    ordered = sorted(candidates, key=lambda item: values[item.candidate_id],
                     reverse=parameters['direction'] == 'descending')
    if operation == 'top_k':
        ordered = ordered[:parameters['k']]
    return replace(candidates, items=tuple(ordered))
