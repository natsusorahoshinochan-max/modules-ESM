"""Pinned native ESMProtein / GenerationConfig adapters."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

from protein_workbench_public.module_api import Tool
from protein_workbench_public.worker_process import run_worker
from .contract import ESM3Request, ESM3Result

SLOT = 'workbench.esm3.generate'
DEFAULTS = {'invalid_ids': [], 'schedule': 'cosine', 'strategy': 'random', 'num_steps': 20,
            'temperature': 1., 'temperature_annealing': True, 'top_p': 1.,
            'condition_on_coordinates_only': True, 'only_compute_backbone_rmsd': False}
ATOM37 = ('N','CA','C','CB','O','CG','CG1','CG2','OG','OG1','SG','CD','CD1','CD2','ND1','ND2','OD1','OD2','SD','CE','CE1','CE2','CE3','NE','NE1','NE2','OE1','OE2','CH2','NH1','NH2','OH','CZ','CZ2','CZ3','NZ','OXT')
TRACKS = ('sequence', 'secondary_structure', 'sasa', 'function_annotations', 'coordinates')
METRICS = ('plddt', 'ptm', 'pae', 'crmsd', 'globularity', 'interface_ptm', 'pair_chains_iptm')


def parameters_for(parameters, *, local):
    allowed = set(DEFAULTS) | ({'seed'} if local else set())
    if set(parameters) - allowed:
        raise ValueError('Unsupported ESM3 parameters: ' + ', '.join(sorted(set(parameters) - allowed)))
    result = {**deepcopy(DEFAULTS), **deepcopy(parameters)}
    if local:
        result.setdefault('seed', 0)
        if type(result['seed']) is not int or not 0 <= result['seed'] <= 2**63 - 1:
            raise ValueError('seed requires an integer in [0, 2**63-1]')
    if type(result['num_steps']) is not int or result['num_steps'] < 1 or (not local and result['num_steps'] > 100):
        raise ValueError('num_steps requires a supported positive integer')
    for name in ('temperature', 'top_p'):
        value = result[name]
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0 or name == 'top_p' and not 0 < value <= 1:
            raise ValueError(f'{name} requires a finite supported number')
    for name in ('temperature_annealing', 'condition_on_coordinates_only', 'only_compute_backbone_rmsd'):
        if type(result[name]) is not bool:
            raise ValueError(f'{name} requires a boolean')
    if result['schedule'] not in ('cosine', 'linear') or result['strategy'] not in ('random', 'entropy'):
        raise ValueError('Unsupported ESM3 schedule or strategy')
    if not isinstance(result['invalid_ids'], list) or any(type(value) is not int or value < 0 for value in result['invalid_ids']):
        raise ValueError('invalid_ids requires nonnegative token IDs')
    return result


def protein_for(request, *, local=False):
    import torch
    from esm.sdk.api import ESMProtein
    from esm.utils.types import FunctionAnnotation
    if not isinstance(request, ESM3Request) or request.track not in ('sequence', 'structure', 'secondary_structure', 'sasa', 'function'):
        raise ValueError('Select an actual ESM3 output track')
    if set(request.tracks) - set(TRACKS) - {'potential_sequence_of_concern'}:
        raise ValueError('Unsupported ESM3 input tracks')
    values = deepcopy(request.tracks)
    sequence = values.get('sequence')
    if not isinstance(sequence, str) or not sequence or any(symbol not in 'ACDEFGHIKLMNPQRSTVWYXBZUO.-|_' for symbol in sequence):
        raise ValueError('ESM3 requires an explicit native sequence/Prompt; unsupported symbols cannot be repaired')
    size = len(sequence)
    for name in ('secondary_structure', 'sasa', 'coordinates'):
        if values.get(name) is not None and len(values[name]) != size:
            raise ValueError(f'{name} must cover every input position')
    if values.get('secondary_structure') is not None and (not isinstance(values['secondary_structure'], str) or any(char not in 'GHITEBSC_' for char in values['secondary_structure'])):
        raise ValueError('secondary_structure requires aligned DSSP8 symbols or _')
    if values.get('sasa') is not None:
        from esm.tokenization.sasa_tokenizer import SASADiscretizingTokenizer
        tokens = set(SASADiscretizingTokenizer().vocab) if local else set()
        if not isinstance(values['sasa'], list) or any(value is not None and not (type(value) in (int, float) and math.isfinite(value)) and not (isinstance(value, str) and value in tokens) for value in values['sasa']):
            raise ValueError('sasa requires aligned finite numeric values or null; local also accepts native SASA vocabulary tokens')
    if values.get('coordinates') is not None:
        coordinates = torch.full((size, 37, 3), float('nan'))
        for index, row in enumerate(values['coordinates']):
            if row is None:
                continue
            if not isinstance(row, dict) or not row or set(row) - set(ATOM37):
                raise ValueError('ESM3 coordinates require supported atom37 names; unsupported atoms cannot be dropped')
            for atom, point in row.items():
                if not isinstance(point, list) or len(point) != 3 or any(type(value) not in (int, float) or not math.isfinite(value) for value in point):
                    raise ValueError('Coordinates require finite XYZ triples')
                coordinates[index, ATOM37.index(atom)] = torch.tensor(point)
        values['coordinates'] = coordinates
    if values.get('function_annotations') is not None:
        annotations = values['function_annotations']
        if not isinstance(annotations, list) or any(not isinstance(row, dict) or set(row) != {'label', 'start', 'end'} or not isinstance(row['label'], str) or type(row['start']) is not int or type(row['end']) is not int or not 1 <= row['start'] <= row['end'] <= size for row in annotations):
            raise ValueError('Function annotations require label and inclusive one-based start/end positions')
        values['function_annotations'] = [FunctionAnnotation(**row) for row in annotations]
    if 'potential_sequence_of_concern' in values and type(values['potential_sequence_of_concern']) is not bool:
        raise ValueError('potential_sequence_of_concern requires a boolean')
    return ESMProtein(**values)


def _json_values(value, *, missing=False):
    if hasattr(value, 'detach'):
        value = value.detach().cpu().tolist()
    if isinstance(value, (list, tuple)):
        return [_json_values(item, missing=missing) for item in value]
    if isinstance(value, dict):
        return {key: _json_values(item, missing=missing) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        if missing and math.isnan(value):
            return None
        raise ValueError('ESM3 returned nonfinite numeric output')
    return value


def save_result(result, config, parameters, runtime, *, seed=None):
    from esm.sdk.api import ESMProtein, ESMProteinError
    if isinstance(result, ESMProteinError):
        raise RuntimeError(f'ESM3 generate failed with status {result.error_code}')
    if not isinstance(result, ESMProtein):
        raise ValueError('ESM3 must return an ESMProtein')
    tracks = {}
    for name in TRACKS:
        value = getattr(result, name)
        if value is not None:
            if name == 'function_annotations':
                value = [{'label': row.label, 'start': row.start, 'end': row.end} for row in value]
            tracks[name] = _json_values(value, missing=name == 'coordinates')
    metrics = {name: _json_values(getattr(result, name)) for name in METRICS if getattr(result, name, None) is not None}
    path = 'esm3-values-' + uuid4().hex + '.json'
    effective = {**parameters, 'num_steps': config.num_steps}
    (runtime.workdir / path).write_text(json.dumps({'tracks': tracks, 'metrics': metrics}, allow_nan=False))
    return ESM3Result({key: value for key, value in tracks.items() if key != 'coordinates'}, path, effective, seed)


def remote_client(settings):
    from esm.sdk import client
    if not settings.get('token'):
        raise ValueError('Configure the Biohub credential in ESM3 module settings')
    return client(model='esm3-open-2024-03', token=settings['token'], url=settings.get('service_url') or 'https://biohub.ai', request_timeout=150)


def create_remote(settings, *, client_factory=remote_client):
    def generate(request, parameters, runtime):
        from esm.sdk.api import GenerationConfig
        values = parameters_for(parameters, local=False)
        protein = protein_for(request)
        config = GenerationConfig(track=request.track, **values)
        if runtime.cancelled:
            raise ValueError('ESM3 generation cancelled')
        client = client_factory(settings)
        try:
            return save_result(client.generate(protein, config), config, values, runtime)
        finally:
            client.close()
    return generate


def create_local(settings):
    def generate(request, parameters, runtime):
        values = parameters_for(parameters, local=True)
        protein_for(request, local=True)  # Refuse unsupported inputs before loading any model.
        payload = {'settings': {name: settings[name] for name in ('model_path', 'device') if name in settings}, 'track': request.track, 'tracks': request.tracks, 'parameters': values,
                   'output': str(runtime.workdir / ('esm3-result-' + uuid4().hex + '.json'))}
        path = runtime.workdir / ('esm3-request-' + uuid4().hex + '.json')
        path.write_text(json.dumps(payload, allow_nan=False))
        try:
            run_worker([settings.get('python') or sys.executable, '-m', 'modules.esm3.worker', str(path)],
                       cwd=Path(__file__).resolve().parents[2], log_path=runtime.workdir / ('esm3-log-' + uuid4().hex), cancelled=lambda: runtime.cancelled, label='ESM3 local generation')
            result = json.loads(Path(payload['output']).read_text())
            return ESM3Result(**result)
        finally:
            path.unlink(missing_ok=True)
    return generate


def tools():
    common = {name: {'default': value} for name, value in DEFAULTS.items()}
    return (Tool('workbench.esm3.biohub', 'ESM3 Biohub open', SLOT, create_remote, parameters=deepcopy(common), capabilities={'tracks': ['sequence', 'structure', 'secondary_structure', 'sasa', 'function'], 'seed': False}),
            Tool('workbench.esm3.local', 'ESM3 native local open', SLOT, create_local, parameters={**deepcopy(common), 'seed': {'type': 'integer', 'default': 0}}, capabilities={'tracks': ['sequence', 'structure', 'secondary_structure', 'sasa', 'function'], 'seed': 'torch.manual_seed; literal 0'}))
