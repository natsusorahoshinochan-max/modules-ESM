"""Fresh external-module source of known observations and downstream report consumer."""
from core.catalog.declarations import AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration, ScientificOperationFactory
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference
from core.catalog.observation import ProducedObservation, ObservationPortSource
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import IntrinsicContextProfile, IntrinsicObservationContext, ScoreCollection, ScoreObservation

METHOD = ExactContractReference('method', 'region_observations.measured')


class Source:
    def execute(self, call):
        axis = call.inputs['axes'].scientific_axes[0]
        return {'scores': ScoreCollection('existing-measurements', (ScoreObservation(
            subject=call.inputs['structures'].candidate_data[0],
            metric=ExactContractReference('metric', 'structure.plddt.per_residue'),
            method=METHOD, context=IntrinsicObservationContext(), source_partition='measurements',
            residue_axis=axis, value=[20.0, None, 80.0, 40.0],
        ),))}


class Receive:
    def execute(self, call):
        return {'statistics': call.inputs['statistics'].value}


def source(context):
    return Source()


def receive(context):
    return Receive()


def binding(name, factory):
    return ExecutionBindingDefinition(
        binding_id='region_observations.' + name + '.direct',
        node_type=ExactContractReference('node_type', 'region_observations.' + name),
        method=METHOD, binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference('region_observations.' + name), factory),
        availability=AvailabilityDeclaration(BehaviorReference('region_observations.available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=False,
        produced_observations=(ProducedObservation(
            output_port='scores', output_partition='measurements',
            metric=ExactContractReference('metric', 'structure.plddt.per_residue'),
            context_profile=IntrinsicContextProfile(), subject_input='structures',
            guaranteed_multiplicity='one', axis_source=ObservationPortSource('input', 'axes'),
        ),) if name == 'source' else (),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id='region_observations', package_module=__name__,
    node_definitions=(DefinitionResource('source.yaml'), DefinitionResource('receive.yaml')),
    methods=(MethodDefinition(METHOD.contract_id, {'name': 'existing-measurements'}, {}, {}, {}),),
    bindings=(binding('source', source), binding('receive', receive)),
)
