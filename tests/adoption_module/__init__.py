"""A tiny external module publishing a declared intrinsic observation."""
from core.catalog.declarations import (AvailabilityDeclaration, AvailabilityResult,
    ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration, ScientificOperationFactory)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.observation import ProducedObservation
from core.catalog.port_contract import BehaviorReference
from core.operation import OperationCall, OperationContext, OperationFailedWithOutputs
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import ScoreCollection, ScoreObservation, IntrinsicObservationContext, IntrinsicContextProfile


class Observe:
    def __init__(self, context: OperationContext) -> None:
        self.method = context.method

    def execute(self, call: OperationCall) -> dict[str, object]:
        outputs = {'scores': ScoreCollection('original-observations', tuple(
            ScoreObservation(reference, ExactContractReference('metric', 'adoption_demo.value'),
                self.method, IntrinsicObservationContext(), 'value', 0.75)
            for reference in call.inputs['candidates'].candidate_data))}
        if call.node_parameters['stop']:
            raise OperationFailedWithOutputs(RuntimeError('Example batch stopped'), outputs)
        return outputs


MODULE_PACKAGE = ModulePackageRegistration(
    package_id='adoption_demo', package_module=__name__,
    node_definitions=(DefinitionResource('observe.yaml'),),
    metric_definitions=(DefinitionResource('metric.yaml'),),
    methods=(MethodDefinition('adoption_demo.method', {'name': 'declared-observation'}, {}, {}, {}),),
    bindings=(ExecutionBindingDefinition(
        binding_id='adoption_demo.observe.direct', node_type=ExactContractReference('node_type', 'adoption_demo.observe'),
        method=ExactContractReference('method', 'adoption_demo.method'), binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('adoption_demo.factory'), Observe),
        availability=AvailabilityDeclaration(BehaviorReference('adoption_demo.available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=True,
        produced_observations=(ProducedObservation('scores', 'value', ExactContractReference('metric', 'adoption_demo.value'),
            IntrinsicContextProfile(), 'candidates', 'one'),),
    ),),
)
