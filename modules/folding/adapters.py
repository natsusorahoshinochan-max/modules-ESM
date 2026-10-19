"""Adapters for the pinned Biohub SDK; environment values stay module settings."""
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from protein_workbench_public.module_api import Tool
from .contract import PredictionResult

LOCAL_DEFAULTS = {'num_loops': 20, 'num_sampling_steps': 200, 'seed': None, 'noise_scale': None, 'step_scale': None, 'max_inference_sigma': None, 'lm_mask_pct': None, 'lm_dropout': 0.3, 'msa_max_depth': 1024, 'msa_column_mask_rate': 0.1, 'include_embeddings': False}
REMOTE_DEFAULTS = {'model': 'esmfold2-fast-2026-05', 'num_loops': 20, 'num_sampling_steps': 100, 'lm_mask_pct': None, 'lm_dropout': 0.3, 'msa_max_depth': 1024, 'msa_column_mask_rate': 0.1, 'include_pae': False, 'include_pair_chains_iptm': False, 'include_embeddings': False}


def parameters_for(values, *, local):
    defaults = LOCAL_DEFAULTS if local else REMOTE_DEFAULTS
    unknown = set(values) - set(defaults) - {'msa'}
    if unknown:
        raise ValueError(f'Unsupported {"local" if local else "remote"} ESMFold2 parameter(s): {", ".join(sorted(unknown))}')
    result = {**defaults, **values}
    for name in ('num_loops', 'num_sampling_steps', 'msa_max_depth', 'seed'):
        value = result.get(name)
        if value is None and name in ('msa_max_depth', 'seed'):
            continue
        if name not in result:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'{name} must be an integer')
        minimum = 0 if name in ('num_loops', 'seed') else 1
        maximum = (2**32 - 1) if name == 'seed' else None if local else (20 if name == 'num_loops' else 16384 if name == 'msa_max_depth' else 100)
        if value < minimum or maximum is not None and value > maximum:
            raise ValueError(f'{name} is outside the supported range')
    for name in ('lm_dropout', 'lm_mask_pct', 'msa_column_mask_rate', 'noise_scale', 'step_scale', 'max_inference_sigma'):
        if name not in result or result[name] is None:
            continue
        value = result[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (name in ('lm_dropout', 'lm_mask_pct', 'msa_column_mask_rate') and value > 1):
            raise ValueError(f'{name} must be a finite supported number')
    for name in ('include_embeddings', 'include_pae', 'include_distogram', 'include_pair_chains_iptm'):
        if name in result and not isinstance(result[name], bool):
            raise ValueError(f'{name} must be boolean')
    if not local and result['model'] not in ('esmfold2-fast-2026-05', 'esmfold2-2026-05'):
        raise ValueError('Select a supported ESMFold2 remote model')
    if 'msa' in result:
        msa = result['msa']
        if not isinstance(msa, dict) or set(msa) - {'sequences', 'deletions'} or not isinstance(msa.get('sequences'), list) or not msa['sequences']:
            raise ValueError('msa must provide aligned sequences and optional deletions')
    return result


def sdk_msa(value, *, msa_type=None):
    if value is None:
        return None
    if msa_type is None:
        from esm.utils.msa import MSA
        msa_type = MSA
    return msa_type.from_state_dict(value)


def _values(value):
    if hasattr(value, 'detach'):
        value = value.detach().cpu()
    if hasattr(value, 'tolist'):
        value = value.tolist()
    if isinstance(value, dict):
        return {str(key): _values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_values(item) for item in value]
    return value


def _decoded(raw, runtime, *, local):
    plddt = _values(getattr(raw, 'plddt', None))
    ptm = _values(getattr(raw, 'ptm', None))
    if not isinstance(plddt, list) or not plddt or ptm is None:
        raise ValueError('ESMFold2 did not return required pLDDT and pTM confidence')
    if isinstance(ptm, list):
        if len(ptm) != 1:
            raise ValueError('ESMFold2 pTM must be scalar')
        ptm = ptm[0]
    protein = raw.complex.to_protein_complex() if local else raw.to_protein_chain()
    import io
    output = io.StringIO()
    protein.to_pdb(output)
    pdb = output.getvalue()
    if not pdb.strip():
        raise ValueError('ESMFold2 returned an empty structure')
    (runtime.workdir / 'esmfold2.pdb').write_text(pdb)
    extras = {}
    for name in ('pae', 'distogram', 'pair_chains_iptm', 'output_embedding_sequence', 'output_embedding_pair_pooled'):
        value = getattr(raw, name, None)
        if value is not None:
            extras[name] = _values(value)
    return PredictionResult('esmfold2.pdb', plddt=plddt, ptm=float(ptm), extras=extras)


def create_remote(settings, *, client_factory=None, config_factory=None):
    """Factories may inject the official SDK boundary for contract verification."""
    def predict(request, parameters, runtime):
        values = parameters_for(parameters, local=False)
        if runtime.cancelled:
            raise ValueError('Prediction cancelled')
        if not settings.get('token'):
            raise ValueError('Configure the Biohub credential in module deployment settings')
        nonlocal client_factory, config_factory
        if client_factory is None:
            from esm.sdk import esmfold2_client
            client_factory = esmfold2_client
        if config_factory is None:
            from esm.sdk.api import FoldingConfig
            config_factory = FoldingConfig
        model = values.pop('model')
        msa = sdk_msa(values.pop('msa', None))
        client = client_factory(model=model, url=settings.get('service_url', 'https://biohub.ai'), token=settings['token'], request_timeout=settings.get('request_timeout', 150))
        try:
            raw = client.fold(sequence=request.sequence, model_name=model, msa=msa, config=config_factory(**values))
            if isinstance(raw, Exception):
                raise ValueError(f'Biohub ESMFold2 failed: {raw}') from raw
            result = _decoded(raw, runtime, local=False)
            return result
        finally:
            client.close()
    return predict


def create_local(settings):
    def predict(request, parameters, runtime):
        values = parameters_for(parameters, local=True)
        if runtime.cancelled:
            raise ValueError('Prediction cancelled')
        python = Path(settings.get('python', sys.executable)).absolute()
        if not python.is_file():
            raise ValueError('Configure an existing ESMFold2 Python executable')
        for key in ('model_path', 'language_model_path'):
            if not settings.get(key) or not Path(settings[key]).is_dir():
                raise ValueError(f'Configure an existing local {key}')
        payload = {'sequence': request.sequence, 'parameters': values, 'settings': {key: str(Path(settings[key]).resolve()) for key in ('model_path', 'language_model_path')}, 'workdir': str(runtime.workdir)}
        payload['settings']['device'] = settings.get('device', 'cpu')
        config = runtime.workdir / 'esmfold2-request.json'
        config.write_text(json.dumps(payload))
        # The supervisor owns the machine lock until the worker and all descendants exit.
        process = subprocess.Popen([sys.executable, '-m', 'protein_workbench_public.model_validation', '--', str(python), '-m', 'modules.folding.local_worker', str(config)], cwd=Path(__file__).resolve().parents[2])
        try:
            while process.poll() is None:
                if runtime.cancelled:
                    process.terminate()
                    process.wait()
                    raise ValueError('Prediction cancelled')
                time.sleep(.1)
            if process.returncode:
                raise ValueError(f'Local ESMFold2 process failed with exit code {process.returncode}; inspect backend log')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
        result = json.loads((runtime.workdir / 'esmfold2-result.json').read_text())
        return PredictionResult(**result)
    return predict


def tools():
    return (
        Tool('workbench.esmfold2.local', 'ESMFold2 · local', 'workbench.predict.structure', create_local, parameters={'defaults': LOCAL_DEFAULTS, 'msa': 'optional aligned protein MSA'}, capabilities={'input': 'one canonical protein chain', 'confidence': 'native pLDDT 0–1 and pTM', 'seed': True}),
        Tool('workbench.esmfold2.remote', 'ESMFold2 · Biohub', 'workbench.predict.structure', create_remote, parameters={'defaults': REMOTE_DEFAULTS, 'msa': 'optional aligned protein MSA', 'lm_mask_pct': 'null delegates model-specific SDK default (fast0.1, full0.0)'}, capabilities={'input': 'one canonical protein chain', 'confidence': 'native pLDDT 0–1 and pTM', 'seed': False}),
    )
