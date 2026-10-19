from protein_workbench_public.module_api import Module, Tool
from modules.folding.contract import PredictionResult


def create(settings):
    def predict(request, parameters, runtime):
        (runtime.workdir / 'manifest.json').write_text(f"{settings['prefix']} seed={parameters['seed']} sequence={request.sequence}")
        return PredictionResult('manifest.json', plddt=[0.8, 0.9, 0.7], ptm=0.75)
    return predict


def module():
    return Module(id='lab.predictor', name='External', tools=(Tool(id='lab.external', name='External prediction', slot='workbench.predict.structure', create=create),))


def consume(call, runtime):
    import json
    from protein_workbench_public.module_api import Delivery, Outcome
    package = call.inputs['source'][0]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    for obj in document['objects']:
        with package.open(obj['structure']['file']) as stream:
            assert stream.read().decode() == obj['sequence']
    (runtime.workdir / 'received.json').write_text(json.dumps({'count': len(document['objects']), 'parameters': call.parameters}))
    return Outcome(outputs={'result': [Delivery('lab.read', 'result', {'result': 'received.json'})]})


def consumer_module():
    from protein_workbench_public.module_api import InputPort, Node, OutputPort
    return Module('lab.consumer', 'Independent prediction reader', nodes=(Node('lab.consume', 'Read predictions', consume,
        inputs={'source': InputPort(('workbench.prediction',))}, outputs={'result': OutputPort('lab.read')}),))
