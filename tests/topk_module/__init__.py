"""Controlled public module; the literal scores are not Provider predictions."""
from core.catalog.declarations import (AvailabilityDeclaration, AvailabilityResult,
    ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration,
    ScientificOperationFactory, UtilityTransformDefinition)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.observation import ProducedObservation, ObservationPortSource
from core.catalog.port_contract import BehaviorReference
from core.operation import OperationCall, OperationContext
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (ScoreCollection, ScoreObservation,
    PairwiseObservationContext, PairwiseParticipant, PairwiseContextProfile)

METRIC = ExactContractReference('metric', 'topk_demo.compatibility')
METHOD = ExactContractReference('method', 'topk_demo.method')
PROFILE = PairwiseContextProfile('subject', 'reference', 'explicit_relation', 'test_scale')


class Observe:
    def execute(self, call: OperationCall) -> dict[str, ScoreCollection]:
        candidates = {item.candidate_id: item for item in call.inputs['subjects'].value}
        values = {'ACDE': .9, 'CDEF': .8, 'DEFG': .7, 'EFGH': .6}
        return {'scores': ScoreCollection('known-compatibility', tuple(
            ScoreObservation(entry.subject, METRIC, METHOD,
                PairwiseObservationContext(PairwiseParticipant('subject', entry.subject),
                    PairwiseParticipant('reference', entry.reference), 'explicit_relation', 'test_scale'),
                'compatibility', values[candidates[entry.subject.candidate_id].data.sequence])
            for entry in call.inputs['relation'].value.entries))}


def build(context: OperationContext) -> Observe:
    return Observe()


def identity(value: float, parameters: object) -> float:
    return value


MODULE_PACKAGE = ModulePackageRegistration(
    package_id='topk_demo', package_module=__name__,
    node_definitions=(DefinitionResource('observe.yaml'),),
    metric_definitions=(DefinitionResource('metric.yaml'),),
    methods=(MethodDefinition('topk_demo.method', {'name': 'controlled-values'}, {}, {}, {}),),
    utility_transforms=(UtilityTransformDefinition('topk_demo.identity', {
        'metric': METRIC, 'method': METHOD, 'context_profile': {'kind': 'pairwise',
        'subject_role': 'subject', 'reference_role': 'reference',
        'pairing_mode': 'explicit_relation', 'normalization': 'test_scale'}}, {},
        BehaviorReference('topk_demo.identity'), identity),),
    bindings=(ExecutionBindingDefinition(
        binding_id='topk_demo.observe.direct', node_type=ExactContractReference('node_type', 'topk_demo.observe'),
        method=METHOD, binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('topk_demo.factory'), build),
        availability=AvailabilityDeclaration(BehaviorReference('topk_demo.available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=False,
        produced_observations=(ProducedObservation('scores', 'compatibility', METRIC, PROFILE, 'subjects', 'one',
            reference_source=ObservationPortSource('input', 'references'),
            pairing_source=ObservationPortSource('input', 'relation')),),
    ),),
)
