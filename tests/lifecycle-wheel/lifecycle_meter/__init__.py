"""Standalone deterministic module used by the user-installation journey."""
from core.catalog.declarations import AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration, ScientificOperationFactory
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from core.catalog.ui import ModuleUiDefinition, NodeEditorDefinition
from core.operation import OperationCall, OperationContext
from datatypes.exact_reference import ExactContractReference


def validate(value):
    if not isinstance(value, dict) or set(value) != {'value', 'note'} or type(value['value']) is not int or type(value['note']) is not str:
        raise ValueError('Expected an integer measurement and note')


def wire(value):
    return value


class Add:
    def execute(self, call: OperationCall):
        previous = call.inputs['reading'].value['value'] if 'reading' in call.inputs else 0
        return {'reading': {'value': previous + call.node_parameters['amount'], 'note': call.node_parameters['note']}}


def build(context: OperationContext):
    return Add()


MODULE_PACKAGE = ModulePackageRegistration(
    package_id='lifecycle_meter', package_module=__name__,
    node_definitions=(DefinitionResource('add.yaml'),),
    methods=(MethodDefinition('lifecycle_meter.add.method', {'name': 'integer-addition'}, {}, {}, {}),),
    port_types=(PortTypeDefinition('lifecycle_meter.reading', BehaviorReference('lifecycle_meter.validate'),
        BehaviorReference('lifecycle_meter.codec'), BehaviorReference('lifecycle_meter.identity'),
        runtime_validator=validate, runtime_to_wire=wire, runtime_from_wire=wire),),
    bindings=(ExecutionBindingDefinition(binding_id='lifecycle_meter.add.direct',
        node_type=ExactContractReference('node_type', 'lifecycle_meter.add'),
        method=ExactContractReference('method', 'lifecycle_meter.add.method'),
        binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('lifecycle_meter.factory'), build),
        availability=AvailabilityDeclaration(BehaviorReference('lifecycle_meter.available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=False),),
    ui_extensions=(ModuleUiDefinition(extension_id='lifecycle_meter.editor', resource_package=__name__, entry='editor.js',
        styles=(), react_major=19, editors=(NodeEditorDefinition('lifecycle_meter.adjust', '调整外部测量', ('lifecycle_meter.add',), 'Adjust'),)),),
)
