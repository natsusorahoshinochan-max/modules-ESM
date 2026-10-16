"""Shared declarations for module-owned, explicitly adopted input nodes."""
from dataclasses import replace

from core.catalog.declarations import (
    AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition,
    MethodDefinition, ModulePackageRegistration, ScientificOperationFactory,
)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference
from core.catalog.result_adoption import ResultSourceDefinition
from core.operation import OperationContext
from core.project.adopted_input import AdoptedInputOperation
from datatypes.exact_reference import ExactContractReference


def _restore(context: OperationContext) -> AdoptedInputOperation:
    return AdoptedInputOperation(context.resources)


def with_adopted_sources(
    package: ModulePackageRegistration,
    sources: tuple[tuple[str, str], ...],
) -> ModulePackageRegistration:
    """Add (local node name, type ID) sources with package-local node YAML.

    Modules explicitly choose supported values. Each node declaration lives at
    ``definitions/<local node name>.yaml`` and exposes a single ``value`` port.
    Restoration uses the existing canonical value contract; no type parser is
    added here. Sources requiring extra outputs or dependencies declare those
    through ResultSourceDefinition directly.
    """
    methods = []
    bindings = []
    declarations = []
    for name, type_id in sources:
        node_id = f'{package.package_id}.{name}'
        method_id = node_id + '.method'
        methods.append(MethodDefinition(
            method_id, {'name': 'restore-adopted-published-value'},
            {'kind': 'none'}, {'kind': 'canonical-value'}, {'kind': 'identity'},
        ))
        bindings.append(ExecutionBindingDefinition(
            binding_id=node_id + '.direct',
            node_type=ExactContractReference('node_type', node_id),
            method=ExactContractReference('method', method_id),
            binding_parameters={}, execution_route='direct',
            factory=ScientificOperationFactory(BehaviorReference(node_id + '/factory'), _restore),
            availability=AvailabilityDeclaration(
                BehaviorReference(node_id + '/availability'), {}, AvailabilityResult.available),
            deterministic=True, cacheable=False,
        ))
        declarations.append(ResultSourceDefinition(type_id, node_id, node_id + '.direct'))
    return replace(
        package,
        node_definitions=package.node_definitions + tuple(
            DefinitionResource(f'definitions/{name}.yaml') for name, _ in sources),
        methods=package.methods + tuple(methods),
        bindings=package.bindings + tuple(bindings),
        result_sources=package.result_sources + tuple(declarations),
    )
