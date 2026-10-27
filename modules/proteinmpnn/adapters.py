"""Native full-backbone ProteinMPNN adapter; no carrier scientific dependencies."""
import json
import math
import sys
from pathlib import Path
from uuid import uuid4

import gemmi

from protein_workbench_public.module_api import Tool
from protein_workbench_public.worker_process import run_worker
from .contract import MPNNResult

SLOT = 'workbench.proteinmpnn.call'
ALPHABET = 'ACDEFGHIKLMNPQRSTVWYX'
DEFAULTS = {'model_name': 'v_48_020', 'use_soluble_model': False, 'backbone_noise': 0.0,
            'seed': 0, 'num_seq_per_target': 1, 'batch_size': 1, 'sampling_temp': [0.1],
            'designed_chains': None, 'fixed_positions': {}, 'tied_positions': [],
            'omit_AAs': 'X', 'bias_AA': {}, 'bias_by_res': {}, 'omit_AA': {}, 'pssm': {},
            'pssm_multi': 0.0, 'pssm_threshold': 0.0, 'pssm_log_odds_flag': False, 'pssm_bias_flag': False}


def prepare_structure(request, workdir):
    path = Path(request.structure_path)
    if path.is_absolute() or not (workdir / path).resolve().is_relative_to(workdir.resolve()):
        raise ValueError('ProteinMPNN structure must be inside runtime.workdir')
    if request.tracks is not None and not request.complete_target:
        raise ValueError('Prepared protein tracks require a complete target')
    if request.complete_target:
        from modules.structure_io.target import read_target
        if request.structure_format != 'mmcif':
            raise ValueError('Complete target requires mmCIF')
        target = read_target((workdir / path).read_bytes())
        if request.tracks is not None:
            tracks = request.tracks
            size = len(target['positions'])
            if set(tracks) != {'sequence', 'coordinates', 'secondary_structure', 'sasa', 'function_annotations'}:
                raise ValueError('ProteinMPNN prepared protein requires five tracks')
            for name in ('sequence', 'coordinates', 'secondary_structure', 'sasa'):
                if not isinstance(tracks[name], list) or len(tracks[name]) != size:
                    raise ValueError(f'ProteinMPNN {name} must cover every target position')
            if any(value is not None for name in ('secondary_structure', 'sasa') for value in tracks[name]) or tracks['function_annotations']:
                raise ValueError('ProteinMPNN supports sequence and backbone inputs; clear unsupported secondary structure, SASA and annotations explicitly')
            for row, residue, atoms in zip(target['positions'], tracks['sequence'], tracks['coordinates'], strict=True):
                if residue is not None and (not isinstance(residue, str) or len(residue) != 1 or residue not in ALPHABET[:-1]):
                    raise ValueError('ProteinMPNN supplied sequence requires canonical residues or null gaps')
                if atoms is not None and (not isinstance(atoms, dict) or any(not isinstance(point, list) or len(point) != 3 or any(type(value) not in (int, float) or not math.isfinite(value) for value in point) for point in atoms.values())):
                    raise ValueError('ProteinMPNN coordinates require finite XYZ triples')
                if atoms is not None and set(atoms) - {'N', 'CA', 'C', 'O'}:
                    raise ValueError('ProteinMPNN prepared coordinates accept only N/CA/C/O; select the backbone atoms explicitly')
                row['residue'], row['atoms'] = residue or 'X', atoms or {}
            target['sequence'] = ''.join(value or 'X' for value in tracks['sequence'])
        author_chains = {row['author_chain'] for row in target['positions']}
        if len(author_chains) != 1 or not next(iter(author_chains)):
            raise ValueError('ProteinMPNN complete target requires one unambiguous author chain')
        chain = next(iter(author_chains))
        entry = {'name': 'target', 'num_of_chains': 1, 'seq': target['sequence'], 'seq_chain_' + chain: target['sequence']}
        coords = {atom + '_chain_' + chain: [] for atom in ('N', 'CA', 'C', 'O')}
        positions = []
        for row in target['positions']:
            for atom in ('N', 'CA', 'C', 'O'):
                if atom not in row['atoms']:
                    raise ValueError(f"ProteinMPNN target position {row['position']} requires {atom} coordinates; no position is omitted")
                coords[atom + '_chain_' + chain].append(row['atoms'][atom])
            if row['residue'] not in (ALPHABET if request.tracks is not None else ALPHABET[:-1]) or type(row['author_number']) is not int:
                raise ValueError('ProteinMPNN complete target requires canonical residues and explicit author numbers')
            positions.append({'chain': chain, 'author_number': row['author_number'], 'insertion_code': row['insertion_code'], 'tool_position': row['position']})
        entry['coords_chain_' + chain] = coords
        if len({(row['author_number'], row['insertion_code']) for row in positions}) != len(positions):
            raise ValueError('ProteinMPNN complete target requires unique real residue numbering')
        return entry, positions
    if request.structure_format == 'pdb':
        content = (workdir / path).read_bytes()
        structure = gemmi.read_pdb_string(content)
        expected_atoms = sum(line.startswith((b'ATOM  ', b'HETATM')) for line in content.splitlines())
    elif request.structure_format == 'mmcif':
        document = gemmi.cif.read_string((workdir / path).read_text())
        if len(document) != 1:
            raise ValueError('ProteinMPNN requires one coordinate data block')
        block = document.sole_block()
        for column in ('auth_asym_id', 'auth_seq_id'):
            if not block.find_values('_atom_site.' + column) or any(value in ('?', '.') for value in block.find_values('_atom_site.' + column)):
                raise ValueError('ProteinMPNN requires actual author chains and residue numbers')
        for column, label in (('pdbx_PDB_ins_code', 'insertion code'), ('label_alt_id', 'alternate location')):
            if any(value not in ('?', '.') and len(gemmi.cif.as_string(value)) > 1 for value in block.find_values('_atom_site.' + column)):
                raise ValueError(f'ProteinMPNN reader cannot preserve a multi-character {label}')
        expected_atoms = len(block.find_values('_atom_site.auth_seq_id'))
        structure = gemmi.make_structure_from_block(block)
    else:
        raise ValueError('ProteinMPNN accepts pdb or mmcif structures')
    if sum(model.count_atom_sites() for model in structure) != expected_atoms:
        raise ValueError('ProteinMPNN could not read every supplied coordinate atom')
    if len(structure) != 1:
        raise ValueError('Select exactly one structure model before ProteinMPNN')
    entry, positions, chain_names = {'name': 'target'}, [], set()
    for chain in structure[0]:
        if chain.name in chain_names or not chain.name:
            raise ValueError('ProteinMPNN requires unique nonempty chain names')
        chain_names.add(chain.name)
        sequence, coords, seen = '', {atom + '_chain_' + chain.name: [] for atom in ('N', 'CA', 'C', 'O')}, set()
        for residue in chain:
            info = gemmi.find_tabulated_residue(residue.name)
            symbol = info.one_letter_code
            if not info.is_amino_acid() or symbol not in ALPHABET[:-1] or not symbol.isupper():
                raise ValueError(f'ProteinMPNN full-backbone model does not support component {residue.name}')
            identity = (residue.seqid.num, residue.seqid.icode.strip())
            if identity[0] is None or identity in seen:
                raise ValueError('ProteinMPNN requires unambiguous real residue numbering')
            seen.add(identity)
            for atom_name in ('N', 'CA', 'C', 'O'):
                atoms = [atom for atom in residue if atom.name == atom_name]
                if len(atoms) != 1 or atoms[0].altloc not in ('\x00', ' '):
                    raise ValueError(f'ProteinMPNN requires one unambiguous {atom_name} atom at {chain.name}:{identity}')
                xyz = list(atoms[0].pos)
                if not all(math.isfinite(value) for value in xyz):
                    raise ValueError('ProteinMPNN requires finite backbone coordinates')
                coords[atom_name + '_chain_' + chain.name].append(xyz)
            sequence += symbol
            positions.append({'chain': chain.name, 'author_number': identity[0], 'insertion_code': identity[1], 'tool_position': len(sequence)})
        if not sequence:
            raise ValueError('ProteinMPNN cannot use an empty chain')
        entry['seq_chain_' + chain.name] = sequence
        entry['coords_chain_' + chain.name] = coords
    if not positions:
        raise ValueError('ProteinMPNN requires protein residues')
    entry.update(num_of_chains=len(chain_names), seq=''.join(entry['seq_chain_' + chain.name] for chain in structure[0]))
    return entry, positions


def create_local(settings):
    def call(request, parameters, runtime):
        if runtime.cancelled:
            raise ValueError('ProteinMPNN cancelled')
        entry, positions = prepare_structure(request, runtime.workdir)
        parameters = dict(parameters)
        if request.tracks is not None:
            chains = [key.removeprefix('seq_chain_') for key in entry if key.startswith('seq_chain_')]
            chain = chains[0]
            supplied = [index + 1 for index, value in enumerate(request.tracks['sequence']) if value is not None]
            native_fixed = parameters.get('fixed_positions', {})
            if not isinstance(native_fixed, dict):
                raise ValueError('ProteinMPNN fixed_positions must map chains to positions')
            parameters['fixed_positions'] = {**native_fixed, chain: list(dict.fromkeys([*native_fixed.get(chain, []), *supplied]))}
        values = parameters_for(parameters, entry, request.sequences)
        if request.tracks is not None and any(request.tracks['sequence'][index - 1] is None for index in values['fixed_positions'].get(chain, [])):
            raise ValueError('ProteinMPNN cannot fix a blank sequence position; supply a residue or remove its native fixed_positions control')
        if request.random_seed is not None and (type(request.random_seed) is not int or not 0 <= request.random_seed <= 2**32 - 1):
            raise ValueError('random_seed must be an actual unsigned 32-bit seed')
        folder = runtime.workdir / ('mpnn-' + uuid4().hex)
        folder.mkdir()
        output = folder / 'result.json'
        payload = {'entry': entry, 'positions': positions, 'sequences': request.sequences, 'parameters': values,
                   'settings': settings, 'actual_seed': values['seed'] or request.random_seed, 'output': str(output)}
        config = folder / 'request.json'
        config.write_text(json.dumps(payload, allow_nan=False))
        run_worker([str(settings.get('python', sys.executable)), '-m', 'modules.proteinmpnn.worker', str(config)],
                   cwd=Path(__file__).resolve().parents[2], log_path=folder / 'worker.log',
                   cancelled=lambda: runtime.cancelled, label='ProteinMPNN')
        result = json.loads(output.read_text())
        expected = values['num_seq_per_target'] * (len(values['sampling_temp']) if request.sequences is None else 1)
        if not isinstance(result.get('samples'), list) or len(result['samples']) != expected:
            raise ValueError('ProteinMPNN returned an incorrect sample count')
        if type(result.get('actual_seed')) is not int or not 0 <= result['actual_seed'] <= 2**32 - 1:
            raise ValueError('ProteinMPNN did not return its actual seed')
        return MPNNResult(positions, result['samples'], result['actual_seed'], values)
    return call


def _parameter_schema():
    labels = {'model_name': {'zh-CN': '模型', 'en': 'Model'}, 'use_soluble_model': {'zh-CN': '可溶性模型', 'en': 'Solubility model'}, 'backbone_noise': {'zh-CN': '主链噪声', 'en': 'Backbone noise'}, 'seed': {'zh-CN': '随机种子', 'en': 'Seed'}, 'num_seq_per_target': {'zh-CN': '候选数量', 'en': 'Samples'}, 'batch_size': {'zh-CN': '批大小', 'en': 'Batch size'}, 'sampling_temp': {'zh-CN': '采样温度', 'en': 'Sampling temperature'}, 'designed_chains': {'zh-CN': '设计链', 'en': 'Design chains'}, 'fixed_positions': {'zh-CN': '保留序列的位置', 'en': 'Fixed sequence positions'}, 'tied_positions': {'zh-CN': '联动位置', 'en': 'Tied positions'}, 'omit_AAs': {'zh-CN': '排除残基', 'en': 'Excluded residues'}, 'bias_AA': {'zh-CN': '残基偏好', 'en': 'Residue bias'}, 'bias_by_res': {'zh-CN': '逐位置偏好', 'en': 'Per-position bias'}, 'omit_AA': {'zh-CN': '逐位置排除', 'en': 'Per-position exclusions'}, 'pssm': 'PSSM', 'pssm_multi': {'zh-CN': 'PSSM 权重', 'en': 'PSSM weight'}, 'pssm_threshold': {'zh-CN': 'PSSM 阈值', 'en': 'PSSM threshold'}, 'pssm_log_odds_flag': {'zh-CN': '使用 PSSM Log-odds', 'en': 'Use PSSM log-odds'}, 'pssm_bias_flag': {'zh-CN': '使用 PSSM 偏好', 'en': 'Use PSSM bias'}}
    fields = {key: {'title': labels[key], 'default': value, 'advanced': key not in ('model_name', 'num_seq_per_target', 'sampling_temp', 'seed')} for key, value in DEFAULTS.items()}
    for key in ('seed', 'num_seq_per_target', 'batch_size'):
        fields[key]['type'] = 'integer'
    fields['model_name']['enum'] = ['v_48_002', 'v_48_010', 'v_48_020', 'v_48_030']
    number = {'type': 'number'}
    positions = {'type': 'array', 'items': {'type': 'integer'}}
    fields['sampling_temp']['items'] = number
    fields['designed_chains'].update(type='array', items={'type': 'string'})
    fields['fixed_positions']['additionalProperties'] = positions
    fields['bias_AA']['additionalProperties'] = number
    fields['bias_by_res']['additionalProperties'] = {'type': 'array', 'items': {'type': 'array', 'items': number}}
    fields['omit_AA']['additionalProperties'] = {'type': 'array', 'items': {'type': 'array', 'prefixItems': [positions, {'type': 'string'}]}}
    fields['tied_positions']['items'] = {'type': 'object', 'additionalProperties': {'type': 'array', 'prefixItems': [positions, {'type': 'array', 'items': number}]}}
    fields['pssm']['additionalProperties'] = {'type': 'object', 'properties': {'pssm_coef': {'type': 'array', 'items': number}, 'pssm_bias': {'type': 'array', 'items': {'type': 'array', 'items': number}}, 'pssm_log_odds': {'type': 'array', 'items': {'type': 'array', 'items': number}}}}
    return fields


def tools():
    return (Tool('workbench.proteinmpnn.local', {'zh-CN': 'ProteinMPNN · 本地', 'en': 'ProteinMPNN · Local'}, SLOT, create_local,
                 parameters=_parameter_schema(), capabilities={'input': 'complete canonical protein N/CA/C/O backbone; explicit full sequence mapping for scoring', 'seed': '0 selects random actual seed'}),)


def parameters_for(parameters, entry, sequences=None):
    from copy import deepcopy
    if not isinstance(parameters, dict) or set(parameters) - set(DEFAULTS):
        raise ValueError('Unsupported ProteinMPNN parameters')
    values = {**deepcopy(DEFAULTS), **deepcopy(parameters)}
    for name in ('seed', 'num_seq_per_target', 'batch_size'):
        value = values[name]
        if type(value) is not int or not (0 if name == 'seed' else 1) <= value <= 2**32 - 1:
            raise ValueError(f'{name} must be an integer in the supported range')
    if values['num_seq_per_target'] % values['batch_size']:
        raise ValueError('num_seq_per_target must be divisible by batch_size; partial batches are not truncated')
    if values['model_name'] not in ('v_48_002', 'v_48_010', 'v_48_020', 'v_48_030'):
        raise ValueError('Select a supported full-backbone model_name')
    for name in ('use_soluble_model', 'pssm_log_odds_flag', 'pssm_bias_flag'):
        if type(values[name]) is not bool:
            raise ValueError(f'{name} must be boolean')
    def number(value, name, low=None, high=None):
        if type(value) not in (int, float) or not math.isfinite(value) or low is not None and value < low or high is not None and value > high:
            raise ValueError(f'{name} requires finite numbers in the supported range')
    number(values['backbone_noise'], 'backbone_noise', 0)
    number(values['pssm_multi'], 'pssm_multi', 0, 1)
    number(values['pssm_threshold'], 'pssm_threshold')
    if not isinstance(values['sampling_temp'], list) or not values['sampling_temp']:
        raise ValueError('sampling_temp must be a nonempty list')
    for temperature in values['sampling_temp']:
        number(temperature, 'sampling_temp', 1e-12)
    chains = {key.removeprefix('seq_chain_'): sequence for key, sequence in entry.items() if key.startswith('seq_chain_')}
    selected = values['designed_chains']
    if selected is None:
        values['designed_chains'] = list(chains)
    elif not isinstance(selected, list) or not selected or any(not isinstance(chain, str) or chain not in chains for chain in selected) or len(set(selected)) != len(selected):
        raise ValueError('designed_chains must select unique actual chain names')
    def chain_rows(name):
        rows = values[name]
        if not isinstance(rows, dict) or set(rows) - set(chains):
            raise ValueError(f'{name} must map actual chain names')
        return rows
    def positions(chain, row):
        if not isinstance(row, list) or not row or any(type(pos) is not int or not 1 <= pos <= len(chains[chain]) for pos in row) or len(set(row)) != len(row):
            raise ValueError('Constraint position must be a unique native 1-based chain position')
    for chain, row in chain_rows('fixed_positions').items():
        if row:
            positions(chain, row)
        elif row != []:
            raise ValueError('fixed_positions requires position lists')
    if not isinstance(values['omit_AAs'], str) or any(aa not in ALPHABET for aa in values['omit_AAs']) or set(values['omit_AAs']) == set(ALPHABET):
        raise ValueError('omit_AAs must contain supported amino acids without omitting every choice')
    if not isinstance(values['bias_AA'], dict) or set(values['bias_AA']) - set(ALPHABET):
        raise ValueError('bias_AA must map alphabet symbols to numeric biases')
    for bias in values['bias_AA'].values():
        number(bias, 'bias_AA')
    for chain, rows in chain_rows('omit_AA').items():
        if not isinstance(rows, list):
            raise ValueError('omit_AA requires native [positions, amino-acids] rows')
        for row in rows:
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError('omit_AA requires native [positions, amino-acids] rows')
            positions(chain, row[0])
            if not isinstance(row[1], (list, str)) or not row[1] or any(aa not in ALPHABET for aa in row[1]):
                raise ValueError('omit_AA requires alphabet symbols')
    for chain, rows in chain_rows('bias_by_res').items():
        if not isinstance(rows, list) or len(rows) != len(chains[chain]):
            raise ValueError('bias_by_res requires one 21-column row per chain position')
        for row in rows:
            if not isinstance(row, list) or len(row) != 21:
                raise ValueError('bias_by_res requires 21 alphabet columns')
            for value in row:
                number(value, 'bias_by_res')
    if not isinstance(values['tied_positions'], list):
        raise ValueError('tied_positions requires a list of native chain-position groups')
    for group in values['tied_positions']:
        if not isinstance(group, dict) or not group or set(group) - set(chains):
            raise ValueError('tied_positions requires actual chain names')
        count = 0
        for chain, row in group.items():
            if not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], list):
                raise ValueError('tied_positions requires [positions, weights]')
            positions(chain, row[0])
            if len(row[0]) != len(row[1]):
                raise ValueError('tied_positions positions and weights must have equal lengths')
            for weight in row[1]:
                number(weight, 'tied weight')
            count += len(row[0])
        if count < 2:
            raise ValueError('tied_positions requires at least two positions per group')
    for chain, data in chain_rows('pssm').items():
        if not isinstance(data, dict) or set(data) != {'pssm_coef', 'pssm_bias', 'pssm_log_odds'}:
            raise ValueError('pssm requires native pssm_coef, pssm_bias and pssm_log_odds')
        for name, rows in data.items():
            if not isinstance(rows, list) or len(rows) != len(chains[chain]):
                raise ValueError('pssm requires complete chain position rows')
            for row in rows:
                if name == 'pssm_coef':
                    number(row, name, 0, 1)
                else:
                    if not isinstance(row, list) or len(row) != 21:
                        raise ValueError('pssm requires 21 alphabet columns')
                    for value in row:
                        number(value, name, 0 if name == 'pssm_bias' else None)
    if sequences is not None:
        if not isinstance(sequences, dict) or set(sequences) != set(chains) or any(not isinstance(sequences[chain], str) or len(sequences[chain]) != len(sequence) or any(aa not in ALPHABET for aa in sequences[chain]) for chain, sequence in chains.items()):
            raise ValueError('Scoring requires complete chain sequence correspondence; no prefix or native-tail repair')
    return values
