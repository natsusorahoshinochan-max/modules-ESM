"""External declarations for public authoring-action behavior tests."""
from core.catalog.declarations import (AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition,
    MethodDefinition, ModulePackageRegistration, ScientificOperationFactory)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.observation import (ProducedObservation, ObservationPortSource, ObservationPropagation,
    ObservationPropagationFilter)
from core.catalog.port_contract import BehaviorReference
from datatypes.exact_reference import ExactContractReference as Ref
from datatypes.observation import IntrinsicContextProfile


def registration():
    operations = ('source', 'proxy', 'pass', 'filtered')
    methods = tuple(MethodDefinition(f'authoring_fixture.{operation}.method', {'name': operation}, {}, {}, {})
                    for operation in operations)
    bindings = tuple(ExecutionBindingDefinition(
        binding_id=f'authoring_fixture.{operation}.direct', node_type=Ref('node_type', f'authoring_fixture.{operation}'),
        method=Ref('method', f'authoring_fixture.{operation}.method'), binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('authoring_fixture/' + operation), lambda context: None),
        availability=AvailabilityDeclaration(BehaviorReference('authoring_fixture/' + operation + '/available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=False,
        produced_observations=((ProducedObservation('scores', 'preserved', Ref('metric', 'selection_fixture.raw'),
            IntrinsicContextProfile(), 'candidates', 'zero_or_more', method_source=ObservationPortSource('input', 'confidence_facts')),) if operation == 'proxy' else ()),
        observation_propagation=(None if operation in {'source', 'proxy'} else ObservationPropagation(
            'pass_through' if operation == 'pass' else 'filter', 'scores', ('scores',),
            None if operation == 'pass' else ObservationPropagationFilter(source_partition='preserved'))),
    ) for operation in operations)
    return ModulePackageRegistration('authoring_fixture', __package__,
        node_definitions=tuple(DefinitionResource(operation + '.yaml') for operation in operations),
        methods=methods, bindings=bindings)
