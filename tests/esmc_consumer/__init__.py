"""A downstream module using the published nominal representation Port."""
from core.catalog.declarations import AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration, ScientificOperationFactory
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference
from core.operation import OperationCall, OperationContext
from datatypes.exact_reference import ExactContractReference

class Consume:
    def execute(self, call: OperationCall) -> dict[str, object]:
        return {'received': call.inputs['representation'].value}

def build(context: OperationContext) -> Consume:
    return Consume()

MODULE_PACKAGE = ModulePackageRegistration(
    package_id='esmc_consumer', package_module=__name__,
    node_definitions=(DefinitionResource('consume.yaml'),),
    methods=(MethodDefinition('esmc_consumer.method', {'name': 'Receive representation'}, {}, {}, {}),),
    bindings=(ExecutionBindingDefinition(
        binding_id='esmc_consumer.receive.direct',
        node_type=ExactContractReference('node_type', 'esmc_consumer.receive'),
        method=ExactContractReference('method', 'esmc_consumer.method'),
        binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('esmc_consumer.factory'), build),
        availability=AvailabilityDeclaration(BehaviorReference('esmc_consumer.available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=False,
    ),),
)
