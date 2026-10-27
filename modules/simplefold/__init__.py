"""Public SimpleFold implementations for prediction and existing-geometry confidence."""
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
    from .confidence import create as create_confidence
    from modules.structure_confidence.contract import SLOT
    return Module(id='workbench.simplefold', name='SimpleFold', tools=(Tool('workbench.simplefold.local', {'zh-CN': 'SimpleFold · 本地', 'en': 'SimpleFold · local torch'}, 'workbench.predict.structure', create, parameters={'defaults': DEFAULTS, 'simplefold_model': {'enum': MODELS, 'title': {'zh-CN': '模型', 'en': 'Model'}}, 'num_steps': {'title': {'zh-CN': '采样步数', 'en': 'Sampling steps'}, 'description': 'positive integer'}, 'tau': {'title': {'zh-CN': '噪声尺度', 'en': 'Noise scale'}, 'description': 'nonnegative noise scale'}, 'seed': {'title': {'zh-CN': '随机种子', 'en': 'Seed'}, 'description': '0–4294967295'}, 'output_format': {'enum': ['pdb', 'mmcif'], 'title': {'zh-CN': '文件格式', 'en': 'File format'}}, 'plddt': {'title': {'zh-CN': '输出 pLDDT', 'en': 'Include pLDDT'}}, 'log_timesteps': {'title': {'zh-CN': '记录采样步骤', 'en': 'Log sampling steps'}}}, capabilities={'input': 'one canonical protein chain; one structure per request', 'backend': 'torch CPU or CUDA selected by upstream availability', 'confidence': 'optional native pLDDT (requires 1.6B latent model and confidence head); no pTM', 'conditioning': False}), Tool('workbench.simplefold.confidence', {'zh-CN': 'SimpleFold · 已有结构 pLDDT', 'en': 'SimpleFold · given geometry pLDDT'}, SLOT, create_confidence, capabilities={'input': 'Canonical protein heavy atoms with complete exact correspondence; no alternate conformations or other components', 'method': 'Original coordinates / 16, t=1, 1.6B latent, pLDDT head; no sampling', 'scale': 'fraction (0–1)'})), settings={'python': {'title': {'zh-CN': 'Python 路径', 'en': 'Python path'}, 'description': 'Existing Python with pinned SimpleFold dependencies'}, 'model_path': {'title': {'zh-CN': '模型目录', 'en': 'Model directory'}, 'description': 'Existing SimpleFold checkpoint directory'}, 'esm2_source': {'title': {'zh-CN': 'ESM2 源码目录', 'en': 'ESM2 source directory'}, 'description': 'Existing Facebook ESM source root'}, 'esm2_checkpoint': {'title': {'zh-CN': 'ESM2 权重文件', 'en': 'ESM2 checkpoint'}, 'description': 'Existing ESM2-3B checkpoint (adjacent contact-regression file required)'}, 'ccd_path': {'title': {'zh-CN': 'CCD 文件', 'en': 'CCD file'}, 'description': 'Existing CCD pickle file'}})
