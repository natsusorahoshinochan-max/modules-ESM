"""Existing measurements with explicit comparison objects for public scenarios."""
from core.catalog.declarations import AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration, ScientificOperationFactory
from core.catalog.definition_resource import DefinitionResource
from core.catalog.observation import ProducedObservation, ObservationPortSource
from core.catalog.port_contract import BehaviorReference
from datatypes.exact_reference import ExactContractReference as Ref
from datatypes.observation import PairwiseContextProfile, PairwiseObservationContext, PairwiseParticipant, ScoreCollection, ScoreObservation


class ExistingComparisons:
    def execute(self, call):
        observations = []
        for index, subject in enumerate(call.inputs['subjects'].candidate_data):
            reference = call.inputs['references'].candidate_data[0]
            context = PairwiseObservationContext(PairwiseParticipant('subject', subject),
                PairwiseParticipant('reference', reference), 'fixed_reference', 'reference-length',
                subject_region=(call.node_parameters['region'],), reference_region=('A:1',))
            observations.append(ScoreObservation(subject, Ref('metric', 'result_action_fixture.measurement'),
                Ref('method', 'result_action_fixture.comparisons.method'), context,
                source_partition='raw', value=call.node_parameters['offset'] + index))
        return {'scores': ScoreCollection('comparisons', observations)}


MODULE_PACKAGE = ModulePackageRegistration(
    'result_action_fixture', __package__, node_definitions=(DefinitionResource('comparisons.yaml'),),
    metric_definitions=(DefinitionResource('measurement.yaml'),),
    methods=(MethodDefinition('result_action_fixture.comparisons.method', {'name': 'existing comparisons'}, {}, {}, {}),),
    bindings=(ExecutionBindingDefinition(
        binding_id='result_action_fixture.comparisons.direct', node_type=Ref('node_type', 'result_action_fixture.comparisons'),
        method=Ref('method', 'result_action_fixture.comparisons.method'), binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('fixture/comparisons'), lambda context: ExistingComparisons()),
        availability=AvailabilityDeclaration(BehaviorReference('fixture/comparisons/available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=False,
        produced_observations=(ProducedObservation(output_port='scores', output_partition='raw',
            metric=Ref('metric', 'result_action_fixture.measurement'), context_profile=PairwiseContextProfile('subject', 'reference', 'fixed_reference', 'reference-length'),
            subject_input='subjects', reference_source=ObservationPortSource('input', 'references'), guaranteed_multiplicity='zero_or_more'),)),),
)
