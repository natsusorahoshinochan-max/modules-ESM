"""An external module exercising public custom-value and viewer contracts."""
import json
from core.catalog.declarations import (
    AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition,
    MethodDefinition, ModulePackageRegistration, ScientificOperationFactory,
)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from core.catalog.result_reading import ResultReaderDefinition
from core.catalog.ui import ModuleUiDefinition, ResultViewerDefinition
from core.operation import OperationCall, OperationContext
from datatypes.exact_reference import ExactContractReference


def validate(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError('Expected an observation object')


def identity(value: object) -> object:
    return value


class Observe:
    def execute(self, call: OperationCall) -> dict[str, object]:
        return {'observation': {'temperature': 23.5}, 'note': {'message': 'room temperature'}}


def build(context: OperationContext) -> Observe:
    return Observe()


def read(encoded: bytes) -> dict[str, object]:
    return json.loads(encoded)['value']


MODULE_PACKAGE = ModulePackageRegistration(
    package_id='reader_demo', package_module=__name__,
    node_definitions=(DefinitionResource('observe.yaml'),),
    methods=(MethodDefinition('reader_demo.method', {'name': 'observation'}, {}, {}, {}),),
    port_types=(PortTypeDefinition(
        'reader_demo.temperature', BehaviorReference('reader_demo.validate'),
        BehaviorReference('reader_demo.codec'), BehaviorReference('reader_demo.identity'),
        runtime_validator=validate, runtime_to_wire=identity, runtime_from_wire=identity,
    ), PortTypeDefinition(
        'reader_demo.note', BehaviorReference('reader_demo.note.validate'),
        BehaviorReference('reader_demo.note.codec'), BehaviorReference('reader_demo.note.identity'),
        runtime_validator=validate, runtime_to_wire=identity, runtime_from_wire=identity,
    )),
    bindings=(ExecutionBindingDefinition(
        binding_id='reader_demo.observe.direct',
        node_type=ExactContractReference('node_type', 'reader_demo.observe'),
        method=ExactContractReference('method', 'reader_demo.method'),
        binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('reader_demo.factory'), build),
        availability=AvailabilityDeclaration(BehaviorReference('reader_demo.available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=False,
    ),),
    result_readers=(
        ResultReaderDefinition('reader_demo.temperature', 'temperature', read),
        ResultReaderDefinition('reader_demo.note', 'sequence', read),
    ),
    ui_extensions=(ModuleUiDefinition(
        extension_id='reader_demo.viewers', resource_package=__name__, entry='viewers.js',
        styles=(), react_major=19, editors=(), viewers=(
            ResultViewerDefinition('reader_demo.celsius', '摄氏温度', 'reader_demo.temperature', 'Celsius', True),
            ResultViewerDefinition('reader_demo.fahrenheit', '华氏温度', 'reader_demo.temperature', 'Fahrenheit'),
        ),
    ),),
)
