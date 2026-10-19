from protein_workbench_public.module_api import Module, Tool
from modules.folding.contract import PredictionResult


def create(settings):
    def predict(request, parameters, runtime):
        (runtime.workdir / 'manifest.json').write_text(f"{settings['prefix']} seed={parameters['seed']} sequence={request.sequence}")
        return PredictionResult('manifest.json', plddt=[0.8, 0.9, 0.7], ptm=0.75)
    return predict


def module():
    return Module(id='lab.predictor', name='External', tools=(Tool(id='lab.external', name='External prediction', slot='workbench.predict.structure', create=create),))
