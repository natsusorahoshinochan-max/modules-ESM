"""Production ProteinMPNN operation and adapter with controlled local Provider."""
from contextlib import contextmanager
from dataclasses import replace
import torch
from core.catalog.declarations import AvailabilityDeclaration, AvailabilityResult, ReadinessDeclaration, ScientificOperationFactory
from core.catalog.port_contract import BehaviorReference
from core.operation import ReadinessResult
from datatypes.sequence import ProteinSequence
from modules.proteinmpnn.adapter import LocalProteinMPNNAdapter
from modules.proteinmpnn.implementation import ProteinMPNNDesignImplementation
from modules.proteinmpnn.package import MODULE_PACKAGE as PRODUCTION_PACKAGE

requests = []
failures = {2}
failure_type = torch.cuda.OutOfMemoryError

class Provider:
    def parse_structure(self, text):
        return [{'name': 'controlled', 'seq_chain_A': 'A', 'seq': 'A', 'coords_chain_A': {}}]

    def activate(self, model_name, backbone_noise):
        pass

    def design(self, request):
        requests.append(request)
        if len(requests) in failures:
            raise failure_type('controlled')
        return [ProteinSequence('A') for _ in range(request.num_sequences)]

class Adapter(LocalProteinMPNNAdapter):
    @contextmanager
    def _provider_execution(self, **kwargs):
        yield Provider()

def build(context):
    return ProteinMPNNDesignImplementation(adapter=Adapter(environment={}, resources=context.resources))

binding = next(b for b in PRODUCTION_PACKAGE.bindings if b.binding_id == 'proteinmpnn.design.local')
MODULE_PACKAGE = replace(PRODUCTION_PACKAGE, bindings=(replace(
    binding,
    factory=ScientificOperationFactory(BehaviorReference('controlled.proteinmpnn.factory'), build),
    availability=AvailabilityDeclaration(BehaviorReference('controlled.proteinmpnn.available'), {}, AvailabilityResult.available),
    readiness=ReadinessDeclaration(BehaviorReference('controlled.proteinmpnn.ready'), {}, lambda env: ReadinessResult(True)),
    environment_fields={},
),))
