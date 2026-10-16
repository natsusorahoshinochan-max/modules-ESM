"""Test-only package: production Operation with a controlled Adapter.

Exercises public Run persistence, not LocalSimpleFoldAdapter activation or models.
"""
from dataclasses import replace

from core.catalog.declarations import AvailabilityDeclaration, AvailabilityResult, ReadinessDeclaration, ScientificOperationFactory
from core.catalog.port_contract import BehaviorReference
from core.operation import ReadinessResult
from datatypes.structure import ProteinStructure
from modules.folding.implementation import SimpleFoldFoldingImplementation
from modules.folding.package import MODULE_PACKAGE as PRODUCTION_PACKAGE
from modules.folding.simplefold_adapter import SimpleFoldAdapterResult, SimpleFoldSampleResult, SimpleFoldProviderError

PDB = 'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C  \nEND\n'
requests = []
failures = {2}


class ControlledAdapter:
    def __init__(self, resources):
        self.resources = resources

    def fold(self, **kwargs):
        with self.resources.engine_invocation(engine_role=kwargs["engine_role"]):
            return self.invoke(**kwargs)

    def invoke(self, **kwargs):
        requests.append(kwargs)
        if len(requests) in failures:
            raise SimpleFoldProviderError('Controlled inference resource failure')
        return SimpleFoldAdapterResult(
            samples=tuple(SimpleFoldSampleResult(i, ProteinStructure(PDB), (80.0,))
                          for i in range(kwargs['num_samples'])),
            effective_call_seed=kwargs['derived_call_seed'],
        )


def build(context):
    return SimpleFoldFoldingImplementation(adapter=ControlledAdapter(context.resources), method=context.method)


binding = next(b for b in PRODUCTION_PACKAGE.bindings if b.binding_id == 'folding.fold.simplefold_local')
MODULE_PACKAGE = replace(PRODUCTION_PACKAGE, bindings=(replace(
    binding,
    factory=ScientificOperationFactory(BehaviorReference('controlled.simplefold.factory'), build),
    availability=AvailabilityDeclaration(BehaviorReference('controlled.simplefold.available'), {}, AvailabilityResult.available),
    readiness=ReadinessDeclaration(BehaviorReference("controlled.simplefold.ready"), {}, lambda environment: ReadinessResult(True)), environment_fields={},
),))
