"""Independent SimpleFold implementation of the public prediction slot."""
import json
import math
from pathlib import Path
import sys

from protein_workbench_public.worker_process import run_worker
from protein_workbench_public.module_api import Module, Tool
from modules.folding.contract import PredictionResult

DEFAULTS = {'simplefold_model': 'simplefold_100M', 'num_steps': 500, 'tau': .1, 'seed': 42, 'plddt': False, 'output_format': 'mmcif', 'log_timesteps': True}
MODELS = tuple(f'simplefold_{size}' for size in ('100M', '360M', '700M', '1.1B', '1.6B', '3B'))


def parameters_for(parameters):
    unknown = set(parameters) - set(DEFAULTS)
    if unknown:
        raise ValueError(f'Unsupported SimpleFold parameter(s): {", ".join(sorted(unknown))}')
    values = {**DEFAULTS, **parameters}
    for name, minimum, maximum in (('num_steps', 1, None), ('seed', 0, 2**32 - 1)):
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum or maximum is not None and value > maximum:
            raise ValueError(f'{name} must be an integer in the supported range')
    if isinstance(values['tau'], bool) or not isinstance(values['tau'], (int, float)) or not math.isfinite(values['tau']) or values['tau'] < 0:
        raise ValueError('tau must be finite and nonnegative')
    if values['simplefold_model'] not in MODELS or values['output_format'] not in ('pdb', 'mmcif'):
        raise ValueError('Unsupported SimpleFold model or output_format')
    if any(not isinstance(values[key], bool) for key in ('plddt', 'log_timesteps')):
        raise ValueError('plddt and log_timesteps must be boolean')
    return values


def create(settings):
    def predict(request, parameters, runtime):
        values = parameters_for(parameters)
        if runtime.cancelled:
            raise ValueError('Prediction cancelled')
        python = Path(settings.get('python', sys.executable)).absolute()
        if not python.is_file():
            raise ValueError('Configure an existing SimpleFold Python executable')
        paths = {}
        for key in ('model_path', 'esm2_source', 'esm2_checkpoint', 'ccd_path'):
            if not settings.get(key) or not Path(settings[key]).exists():
                raise ValueError(f'Configure existing SimpleFold {key}')
            paths[key] = str(Path(settings[key]).resolve())
        model_root = Path(paths['model_path'])
        required = [model_root / f"{values['simplefold_model']}.ckpt", Path(paths['esm2_checkpoint']).with_name(Path(paths['esm2_checkpoint']).stem + '-contact-regression.pt')]
        if values['plddt']:
            required.extend((model_root / 'plddt.ckpt', model_root / 'simplefold_1.6B.ckpt'))
        for path in required:
            if not path.is_file():
                raise ValueError(f'SimpleFold requires existing resource: {path}')
        config = runtime.workdir / 'simplefold-request.json'
        config.write_text(json.dumps({'sequence': request.sequence, 'parameters': values, 'settings': paths, 'workdir': str(runtime.workdir)}))
        run_worker(
            [str(python), '-m', 'modules.simplefold.worker', str(config)],
            cwd=Path(__file__).resolve().parents[2],
            log_path=runtime.workdir / 'simplefold-worker.log',
            cancelled=lambda: runtime.cancelled, label='SimpleFold',
        )
        return PredictionResult(**json.loads((runtime.workdir / 'simplefold-result.json').read_text()))
    return predict


def module():
    return Module(id='workbench.simplefold', name='SimpleFold', tools=(Tool('workbench.simplefold.local', 'SimpleFold · local torch', 'workbench.predict.structure', create, parameters={'defaults': DEFAULTS, 'simplefold_model': MODELS, 'num_steps': 'positive integer', 'tau': 'nonnegative noise scale', 'seed': '0–4294967295', 'output_format': ['pdb', 'mmcif']}, capabilities={'input': 'one canonical protein chain; one structure per request', 'backend': 'torch CPU or CUDA selected by upstream availability', 'confidence': 'optional native pLDDT (requires 1.6B latent model and confidence head); no pTM', 'conditioning': False}),), settings={'python': 'Existing Python with pinned SimpleFold dependencies', 'model_path': 'Existing SimpleFold checkpoint directory', 'esm2_source': 'Existing Facebook ESM source root', 'esm2_checkpoint': 'Existing ESM2-3B checkpoint (adjacent contact-regression file required)', 'ccd_path': 'Existing CCD pickle file'})
