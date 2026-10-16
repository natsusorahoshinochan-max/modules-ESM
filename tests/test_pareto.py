"""Pareto's public raw-value selection boundary (spec #126)."""
from dataclasses import replace
import unittest

from datatypes.candidate import Candidate, CandidateCollection, CandidateDataReference
from datatypes.exact_reference import ExactContractReference as Ref
from datatypes.observation import IntrinsicObservationContext, ScoreCollection, ScoreObservation
from datatypes.sequence import ProteinSequence
from modules.selection.compute import SelectionError, select_candidates


class ParetoTests(unittest.TestCase):
    def test_equal_values_do_not_dominate_and_both_directions_use_raw_values(self):
        population = CandidateCollection('study', 'protein.sequence', tuple(
            Candidate(name, ProteinSequence(sequence), parent_ids=('source',), metadata={'label': name})
            for name, sequence in [('z', 'AA'), ('a', 'AC'), ('tradeoff', 'AD'), ('dominated', 'AE')]))
        references = tuple(CandidateDataReference(item.candidate_id, 'protein.sequence', 'sha256:' + str(index) * 64)
            for index, item in enumerate(population))
        def score(values):
            return ScoreCollection('measurements', tuple(ScoreObservation(reference, Ref('metric', 'study.raw'),
                Ref('method', 'study.measured'), IntrinsicObservationContext(), 'raw', value)
                for reference, value in zip(references, values, strict=True)))
        selection = {'score_input': 'yield', 'metric_id': 'study.raw', 'method_id': 'study.measured',
            'source_partition': 'raw', 'context': {'kind': 'intrinsic'}}
        parameters = {'objectives': [{'selection': selection, 'direction': 'descending'},
            {'selection': dict(selection, score_input='cost'), 'direction': 'ascending'}]}
        result = select_candidates(population, references,
            {'yield': (score([12, 12, 8, 8]),), 'cost': (score([-2, -2, -9, -2]),)}, parameters, operation='pareto')
        self.assertEqual(result, replace(population, items=population.items[:3]))
        for actual, original in zip(result, population):
            self.assertIs(actual, original)

    def test_reference_order_does_not_change_candidate_score_association(self):
        population = CandidateCollection('study', 'protein.sequence', (
            Candidate('a', ProteinSequence('AA')), Candidate('b', ProteinSequence('AC'))))
        first = CandidateDataReference('a', 'protein.sequence', 'sha256:' + '1' * 64)
        second = CandidateDataReference('b', 'protein.sequence', 'sha256:' + '2' * 64)
        scores = ScoreCollection('scores', tuple(ScoreObservation(reference, Ref('metric', 'study.raw'),
            Ref('method', 'study.measured'), IntrinsicObservationContext(), 'raw', value)
            for reference, value in [(first, 10), (second, 1)]))
        parameters = {'objectives': [{'selection': {'score_input': 'score', 'metric_id': 'study.raw',
            'method_id': 'study.measured', 'source_partition': 'raw', 'context': {'kind': 'intrinsic'}},
            'direction': 'descending'}]}
        result = select_candidates(population, (second, first), {'score': (scores,)}, parameters, operation='pareto')
        self.assertEqual(result, replace(population, items=(population.items[0],)))

    def test_missing_or_ambiguous_required_measurements_use_the_shared_failure_rule(self):
        candidate = Candidate('candidate', ProteinSequence('AA'))
        population = CandidateCollection('study', 'protein.sequence', (candidate,))
        reference = CandidateDataReference('candidate', 'protein.sequence', 'sha256:' + '1' * 64)
        observation = ScoreObservation(reference, Ref('metric', 'study.raw'), Ref('method', 'study.measured'),
            IntrinsicObservationContext(), 'raw', 12)
        selection = {'score_input': 'score', 'metric_id': 'study.raw', 'method_id': 'study.measured',
            'source_partition': 'raw', 'context': {'kind': 'intrinsic'}}
        for measurements, code in [((), 'missing_score'), ((replace(observation, value=None),), 'missing_score'),
                ((observation, replace(observation, value=8)), 'ambiguous_score')]:
            with self.subTest(code=code, count=len(measurements)):
                with self.assertRaises(SelectionError) as failure:
                    select_candidates(population, (reference,), {'score': (ScoreCollection('scores', measurements),)},
                        {'objectives': [{'selection': selection, 'direction': 'descending'}]}, operation='pareto')
                self.assertEqual(failure.exception.code, code)

    def test_empty_population_returns_an_empty_original_collection(self):
        population = CandidateCollection('study', 'protein.sequence', ())
        result = select_candidates(population, (), {}, {'objectives': [{'selection': {
            'score_input': 'score', 'metric_id': 'study.raw', 'method_id': 'study.measured',
            'source_partition': 'raw', 'context': {'kind': 'intrinsic'}}, 'direction': 'ascending'}]}, operation='pareto')
        self.assertEqual(result, population)


if __name__ == '__main__':
    unittest.main()
