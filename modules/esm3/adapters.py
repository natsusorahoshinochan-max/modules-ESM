"""Pinned native ESMProtein / GenerationConfig adapters."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

from protein_workbench_public.module_api import Tool
from protein_workbench_public.worker_process import run_worker
from modules.generation.contract import GenerateRequest, GenerateResult

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


def protein_for(request, *, local=False, workdir=None):
    import torch
    from esm.sdk.api import ESMProtein
    from esm.utils.types import FunctionAnnotation
    if not isinstance(request, GenerateRequest) or request.track not in ('sequence', 'structure', 'secondary_structure', 'sasa', 'function'):
        raise ValueError('Select an actual ESM3 output track')
    if set(request.tracks) - set(TRACKS) - {'potential_sequence_of_concern'}:
        raise ValueError('Unsupported ESM3 input tracks')
    values = deepcopy(request.tracks)
    if request.target_file is not None:
        from modules.structure_io.target import read_target
        if workdir is None:
            raise ValueError('Complete target requires the invocation workdir')
        path = Path(request.target_file)
        if path.is_absolute() or not (workdir / path).resolve().is_relative_to(workdir.resolve()):
            raise ValueError('Target file must belong to runtime.workdir')
        target = read_target((workdir / path).read_bytes())
        size = len(target['positions'])
        if set(request.conditions) != {'sequence', 'coordinates'}:
            raise ValueError('Target requires explicit sequence and coordinate conditions')
        prompt, coordinates = ['_'] * size, [None] * size
        seen = set()
        for row in request.conditions['sequence']:
            position, residue = row.get('position'), row.get('residue')
            if type(position) is not int or not 1 <= position <= size or position in seen or not isinstance(residue, str) or len(residue) != 1 or residue == '_' or residue != target['sequence'][position - 1]:
                raise ValueError('Sequence conditions must match unique complete target positions')
            seen.add(position)
            prompt[position - 1] = residue
        seen = set()
        for row in request.conditions['coordinates']:
            position, names = row.get('position'), row.get('atoms')
            if type(position) is not int or not 1 <= position <= size or position in seen or not isinstance(names, list) or not names or len(set(names)) != len(names):
                raise ValueError('Coordinate conditions require unique complete target positions and atom names')
            if set(names) - set(ATOM37):
                raise ValueError('ESM3 coordinate conditions require supported atom37 names')
            available = target['positions'][position - 1]['atoms']
            if set(names) - set(available):
                raise ValueError(f'Coordinate condition at target position {position} names missing atoms')
            seen.add(position)
            coordinates[position - 1] = {name: available[name] for name in names}
        expected = ''.join(prompt)
        if request.track == 'sequence' and values.get('sequence', expected) != expected:
            raise ValueError('Sequence Prompt disagrees with target conditions')
        sequence = values.get('sequence', expected)
        if len(sequence) != size or any(fixed != '_' and fixed != actual for fixed, actual in zip(expected, sequence, strict=True)):
            raise ValueError('Generated sequence must retain complete target positions and fixed residues')
        if 'coordinates' in values:
            raise ValueError('Target coordinate conditions must come from the complete target file')
        values.update(sequence=sequence, coordinates=coordinates if seen else None)
    elif request.conditions:
        raise ValueError('Position conditions require a complete target file')
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
    role = 'absent'
    structure_file = None
    if 'coordinates' in tracks:
        role = 'generated_structure' if config.track == 'structure' else 'input_conditions'
        if config.track == 'structure':
            structure_file = write_structure(tracks, runtime)
    elif config.track == 'structure':
        raise ValueError('ESM3 structure generation returned no coordinates')
    return GenerateResult({key: value for key, value in tracks.items() if key != 'coordinates'}, path, effective, seed, role, structure_file)



def write_structure(tracks, runtime):
    """Encode the tool's private atom37 axis as an ordinary completed mmCIF."""
    import gemmi
    sequence, coordinates = tracks.get('sequence'), tracks['coordinates']
    if not isinstance(sequence, str) or not isinstance(coordinates, list) or len(coordinates) != len(sequence):
        raise ValueError('Structure generation must cover every actual sequence position')
    points = []
    for row in coordinates:
        if not isinstance(row, list) or len(row) != 37 or any(not isinstance(point, list) or len(point) != 3 for point in row):
            raise ValueError('ESM3 structure output requires its complete native atom axis')
        points.extend(row)
    if not any(all(type(value) in (int, float) and math.isfinite(value) for value in point) for point in points):
        raise ValueError('ESM3 structure output has no finite atoms')
    if any(letter not in 'ACDEFGHIKLMNPQRSTVWY' for letter in sequence):
        return None  # Extended native results remain available through their native file.
    if any(not any(all(value is not None for value in point) for point in row) for row in coordinates):
        return None
    structure, model, chain = gemmi.Structure(), gemmi.Model(1), gemmi.Chain('A')
    three = dict(zip('ACDEFGHIKLMNPQRSTVWY', ('ALA','CYS','ASP','GLU','PHE','GLY','HIS','ILE','LYS','LEU','MET','ASN','PRO','GLN','ARG','SER','THR','VAL','TRP','TYR'), strict=True))
    for index, (letter, row) in enumerate(zip(sequence, coordinates, strict=True), 1):
        residue = gemmi.Residue()
        residue.name, residue.seqid, residue.het_flag = three[letter], gemmi.SeqId(index, ' '), 'A'
        for name, point in zip(ATOM37, row, strict=True):
            if point == [None, None, None]:
                continue
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in point):
                raise ValueError('ESM3 cannot encode partial or nonfinite atom coordinates')
            atom = gemmi.Atom()
            atom.name, atom.element, atom.pos, atom.occ, atom.b_iso = name, gemmi.Element(name[0]), gemmi.Position(*point), 1.0, 0.0
            residue.add_atom(atom)
        chain.add_residue(residue)
    model.add_chain(chain); structure.add_model(model); structure.setup_entities()
    path = 'esm3-structure-' + uuid4().hex + '.cif'
    structure.make_mmcif_document().write_file(str(runtime.workdir / path))
    return path


def remote_client(settings):
    from esm.sdk import client
    if not settings.get('token'):
        raise ValueError('Configure the Biohub credential in ESM3 module settings')
    return client(model='esm3-open-2024-03', token=settings['token'], url=settings.get('service_url') or 'https://biohub.ai', request_timeout=150)


def create_remote(settings, *, client_factory=remote_client):
    def generate(request, parameters, runtime):
        from esm.sdk.api import GenerationConfig
        values = parameters_for(parameters, local=False)
        protein = protein_for(request, workdir=runtime.workdir)
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
        protein_for(request, local=True, workdir=runtime.workdir)  # Refuse unsupported inputs before loading any model.
        payload = {'settings': {name: settings[name] for name in ('model_path', 'device') if name in settings}, 'track': request.track, 'tracks': request.tracks, 'target_file': request.target_file, 'conditions': request.conditions, 'parameters': values,
                   'output': str(runtime.workdir / ('esm3-result-' + uuid4().hex + '.json'))}
        path = runtime.workdir / ('esm3-request-' + uuid4().hex + '.json')
        path.write_text(json.dumps(payload, allow_nan=False))
        try:
            run_worker([settings.get('python') or sys.executable, '-m', 'modules.esm3.worker', str(path)],
                       cwd=Path(__file__).resolve().parents[2], log_path=runtime.workdir / ('esm3-log-' + uuid4().hex), cancelled=lambda: runtime.cancelled, label='ESM3 local generation')
            result = json.loads(Path(payload['output']).read_text())
            return GenerateResult(**result)
        finally:
            path.unlink(missing_ok=True)
    return generate


def tools():
    common = {name: {'default': value} for name, value in DEFAULTS.items()}
    return (Tool('workbench.esm3.biohub', 'ESM3 Biohub open', SLOT, create_remote, parameters=deepcopy(common), capabilities={'tracks': ['sequence', 'structure', 'secondary_structure', 'sasa', 'function'], 'seed': False}),
            Tool('workbench.esm3.local', 'ESM3 native local open', SLOT, create_local, parameters={**deepcopy(common), 'seed': {'type': 'integer', 'default': 0}}, capabilities={'tracks': ['sequence', 'structure', 'secondary_structure', 'sasa', 'function'], 'seed': 'torch.manual_seed; literal 0'}))
