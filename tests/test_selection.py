"""Selection module public numerical and matching behavior (spec #126)."""
import unittest

from datatypes.candidate import Candidate, CandidateCollection, CandidateDataReference
from datatypes.sequence import ProteinSequence
from datatypes.exact_reference import ExactContractReference, ResidueAxisReference
from datatypes.residue import ResidueLayout
from datatypes.observation import IntrinsicObservationContext, ScoreCollection, ScoreObservation
from modules.selection.compute import SelectionError, select_candidates
from dataclasses import replace, asdict
from datatypes.observation import (CalibrationObservationContext, PairwiseObservationContext, PairwiseParticipant, CandidateRelation, CandidateRelationEntry)


class RawSelectionTests(unittest.TestCase):
    def test_pairwise_reference_choice_resolves_real_evaluation_without_using_parentage(self):
        candidates = CandidateCollection('input', 'protein.sequence', (Candidate('c', ProteinSequence('AA'), parent_ids=('unrelated',)),))
        subject = CandidateDataReference('c', 'protein.sequence', 'sha256:' + '1' * 64)
        first = CandidateDataReference('ref-a', 'protein.structure', 'sha256:' + '2' * 64)
        second = CandidateDataReference('ref-b', 'protein.structure', 'sha256:' + '3' * 64)
        def measurement(reference, value):
            return ScoreObservation(subject, ExactContractReference('metric', 'test.raw'),
                ExactContractReference('method', 'test.measure'), PairwiseObservationContext(
                    PairwiseParticipant('subject', subject), PairwiseParticipant('reference', reference),
                    'explicit_relation', 'reference-length'), 'raw', value)
        parameters = {'selection': {'score_input': 'score-a', 'metric_id': 'test.raw', 'method_id': 'test.measure',
            'source_partition': 'raw', 'context': {'kind': 'pairwise', 'subject_role': 'subject',
                'reference_role': 'reference', 'pairing_mode': 'explicit_relation', 'normalization': 'reference-length'}},
            'direction': 'ascending'}
        score_inputs = {'score-a': (ScoreCollection('scores', (measurement(first, 4), measurement(second, 2))),)}
        with self.assertRaisesRegex(SelectionError, 'exactly one'):
            select_candidates(candidates, (subject,), score_inputs, parameters, operation='sort')
        parameters['selection']['reference'] = {'candidate_id': 'ref-b', 'data_type_id': 'protein.structure',
                                               'content_digest': 'sha256:' + '3' * 64}
        self.assertEqual(list(select_candidates(candidates, (subject,), score_inputs, parameters, operation='sort')), list(candidates))

    def test_different_candidates_can_use_their_own_explicit_reference(self):
        refs = tuple(CandidateDataReference(name, 'protein.sequence', 'sha256:' + char * 64)
                     for name, char in [('one', '1'), ('two', '2')])
        references = tuple(CandidateDataReference(name, 'protein.structure', 'sha256:' + char * 64)
                           for name, char in [('ref-one', '3'), ('ref-two', '4')])
        candidates = CandidateCollection('input', 'protein.sequence', (Candidate('one', ProteinSequence('AA')), Candidate('two', ProteinSequence('AC'))))
        entries = tuple(ScoreObservation(subject, ExactContractReference('metric', 'test.raw'),
            ExactContractReference('method', 'test.measure'), PairwiseObservationContext(
                PairwiseParticipant('subject', subject), PairwiseParticipant('reference', reference),
                'explicit_relation', 'reference-length'), 'raw', value)
            for subject in refs for reference, value in zip(references, (2, 8)))
        relation = CandidateRelation(tuple(CandidateRelationEntry(subject, reference) for subject, reference in zip(refs, references)))
        parameters = {'selection': {'score_input': 'score-a', 'metric_id': 'test.raw', 'method_id': 'test.measure',
            'source_partition': 'raw', 'context': {'kind': 'pairwise', 'subject_role': 'subject',
                'reference_role': 'reference', 'pairing_mode': 'explicit_relation', 'normalization': 'reference-length'},
            'relation_input': 'study-relations'}, 'direction': 'descending'}
        result = select_candidates(candidates, refs, {'score-a': (ScoreCollection('scores', entries),)}, parameters,
            operation='sort', relation_inputs={'study-relations': (relation,)})
        self.assertEqual(list(result), [candidates.items[1], candidates.items[0]])

    def test_saved_exact_axis_choice_distinguishes_regions_of_the_same_measurement(self):
        refs = tuple(CandidateDataReference(name, 'protein.sequence', 'sha256:' + char * 64)
                     for name, char in [('one', '1'), ('two', '2')])
        candidates = CandidateCollection('input', 'protein.sequence', (Candidate('one', ProteinSequence('AA')), Candidate('two', ProteinSequence('AC'))))
        entries, choices = [], []
        for subject, values in zip(refs, [(1, 8), (9, 2)]):
            for region, value in zip(('A:1', 'A:2'), values):
                axis = ResidueAxisReference('prediction_input', ExactContractReference('port_type', 'protein.sequence'),
                    'sha256:' + ('3' if region == 'A:1' else '4') * 64, subject, ResidueLayout((region,)))
                entries.append(ScoreObservation(subject, ExactContractReference('metric', 'test.raw'),
                    ExactContractReference('method', 'test.measure'), IntrinsicObservationContext(), 'raw', value, axis))
                if region == 'A:2':
                    choices.append({'subject': asdict(subject), 'context': {'kind': 'intrinsic'}, 'residue_axis': asdict(axis)})
        parameters = {'selection': {'score_input': 'score-a', 'metric_id': 'test.raw', 'method_id': 'test.measure',
            'source_partition': 'raw', 'context': {'kind': 'intrinsic'}, 'exact_contexts': choices}, 'direction': 'descending'}
        result = select_candidates(candidates, refs, {'score-a': (ScoreCollection('scores', entries),)}, parameters, operation='sort')
        self.assertEqual(list(result), list(candidates))

    def test_pairwise_region_choices_use_recorded_residues_and_published_context(self):
        from core.catalog.builtins import builtin_port_types
        from modules.selection.published_reading import read_scores
        subject = CandidateDataReference('c', 'protein.sequence', 'sha256:' + '1' * 64)
        reference = CandidateDataReference('ref', 'protein.structure', 'sha256:' + '2' * 64)
        context = PairwiseObservationContext(PairwiseParticipant('subject', subject),
            PairwiseParticipant('reference', reference), 'fixed_reference', 'reference-length',
            subject_region=('A:1',), reference_region=('B:9',))
        chosen = ScoreObservation(subject, ExactContractReference('metric', 'test.raw'),
            ExactContractReference('method', 'test.measure'), context, 'raw', 4)
        other = replace(chosen, context=replace(context, subject_region=('A:2',), reference_region=('B:10',)))
        collection = ScoreCollection('scores', (chosen, other))
        port = next(port for port in builtin_port_types() if port.type_id == 'score.collection')
        published = read_scores(port.encode(collection))['entries'][0]
        parameters = {'selection': {'score_input': 'score-a', 'metric_id': 'test.raw', 'method_id': 'test.measure',
            'source_partition': 'raw', 'context': published['context_profile'],
            'exact_contexts': [{'subject': published['subject'], 'context': published['context']}]}, 'direction': 'descending'}
        candidates = CandidateCollection('input', 'protein.sequence', (Candidate('c', ProteinSequence('AA')),))
        result = select_candidates(candidates, (subject,), {'score-a': (collection,)}, parameters, operation='sort')
        self.assertEqual(list(result), list(candidates))

    def test_raw_sort_rejects_residue_vectors_instead_of_ranking_lists(self):
        refs = tuple(CandidateDataReference(name, 'protein.sequence', 'sha256:' + char * 64)
                     for name, char in [('one', '1'), ('two', '2')])
        candidates = CandidateCollection('input', 'protein.sequence', (Candidate('one', ProteinSequence('AA')), Candidate('two', ProteinSequence('AC'))))
        scores = ScoreCollection('scores', tuple(ScoreObservation(subject, ExactContractReference('metric', 'test.residue'),
            ExactContractReference('method', 'test.measure'), IntrinsicObservationContext(), 'raw', value)
            for subject, value in zip(refs, [[1, 100], [2, 0]])))
        with self.assertRaisesRegex(SelectionError, 'scalar'):
            select_candidates(candidates, refs, {'score-a': (scores,)}, {
                'selection': {'score_input': 'score-a', 'metric_id': 'test.residue', 'method_id': 'test.measure',
                    'source_partition': 'raw', 'context': {'kind': 'intrinsic'}}, 'direction': 'ascending'}, operation='sort')

    def test_empty_population_needs_no_observation_or_relation_values(self):
        empty = CandidateCollection('empty', 'protein.sequence', ())
        result = select_candidates(empty, (), {}, {'selection': {
            'score_input': 'scores', 'metric_id': 'test.raw', 'method_id': 'test.measure',
            'source_partition': 'raw', 'context': {'kind': 'intrinsic'}, 'relation_input': 'relations'},
            'direction': 'descending', 'k': 5}, operation='top_k', relation_inputs={})
        self.assertEqual(list(result), [])

    def test_a_null_required_measurement_stops_selection(self):
        candidate = Candidate('c', ProteinSequence('AA'))
        reference = CandidateDataReference('c', 'protein.sequence', 'sha256:' + '1' * 64)
        score = ScoreObservation(reference, ExactContractReference('metric', 'test.raw'),
            ExactContractReference('method', 'test.measure'), IntrinsicObservationContext(), 'raw', None)
        with self.assertRaisesRegex(SelectionError, 'missing'):
            select_candidates(CandidateCollection('input', 'protein.sequence', (candidate,)), (reference,),
                {'score-a': (ScoreCollection('scores', (score,)),)}, {
                    'selection': {'score_input': 'score-a', 'metric_id': 'test.raw', 'method_id': 'test.measure',
                                  'source_partition': 'raw', 'context': {'kind': 'intrinsic'}},
                    'direction': 'ascending'}, operation='sort')

    def test_selected_context_excludes_other_measurements(self):
        candidates = CandidateCollection('input', 'protein.sequence', (Candidate('c', ProteinSequence('AA')),))
        reference = CandidateDataReference('c', 'protein.sequence', 'sha256:' + '1' * 64)
        observation = ScoreObservation(reference, ExactContractReference('metric', 'test.raw'),
            ExactContractReference('method', 'test.measure'), IntrinsicObservationContext(), 'raw', 12)
        other = replace(observation, context=CalibrationObservationContext('baseline', 3, 'raw', 'population'))
        result = select_candidates(candidates, (reference,), {'score-a': (ScoreCollection('scores', (observation, other)),)}, {
            'selection': {'score_input': 'score-a', 'metric_id': 'test.raw', 'method_id': 'test.measure',
                          'source_partition': 'raw', 'context': {'kind': 'intrinsic'}},
            'direction': 'ascending'}, operation='sort')
        self.assertEqual(list(result), list(candidates))

    def test_raw_top_k_preserves_input_ties_without_a_transform(self):
        candidates = CandidateCollection('input', 'protein.sequence', (
            Candidate('z', ProteinSequence('AA')), Candidate('a', ProteinSequence('AC')), Candidate('m', ProteinSequence('AD')),
        ))
        refs = tuple(CandidateDataReference(item.candidate_id, 'protein.sequence', 'sha256:' + char * 64)
                     for item, char in zip(candidates, '123'))
        scores = ScoreCollection('scores', tuple(ScoreObservation(
            subject=ref, metric=ExactContractReference('metric', 'test.raw'),
            method=ExactContractReference('method', 'test.measure'),
            context=IntrinsicObservationContext(), source_partition='raw', value=value,
        ) for ref, value in zip(refs, (12, 12, -8))))
        result = select_candidates(candidates, refs, {'score-a': (scores,)}, {
            'selection': {'score_input': 'score-a', 'metric_id': 'test.raw',
                          'method_id': 'test.measure', 'source_partition': 'raw',
                          'context': {'kind': 'intrinsic'}},
            'direction': 'descending', 'k': 1,
        }, operation='top_k')
        self.assertEqual(list(result), [candidates.items[0]])


if __name__ == '__main__':
    unittest.main()
