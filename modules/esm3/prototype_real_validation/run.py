"""THROWAWAY: exercise proposed module seams with real scientific tools.

Run using the existing project environment; evidence stays under --output.
No application database, production module, model weights or upstream source is edited.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
CHECKS: list[dict] = []


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def check(name: str, condition, **evidence):
    if not bool(condition):
        raise AssertionError(name)
    CHECKS.append({'check': name, 'status': 'passed', **evidence})


def expect_rejection(name, callback, contains):
    try:
        callback()
    except ValueError as error:
        check(name, contains in str(error), diagnostic=str(error))
        return str(error)
    raise AssertionError(name + ': unsupported input was accepted')


def load_rows(pdb: Path):
    import gemmi
    structure = gemmi.read_structure(str(pdb))
    selected = []
    excluded = []
    for chain in structure[0]:
        for residue in chain:
            info = gemmi.find_tabulated_residue(residue.name)
            if chain.name != 'A' or not info.is_amino_acid():
                excluded.append({'chain': chain.name, 'author_number': residue.seqid.num,
                                 'insertion_code': residue.seqid.icode.strip(), 'name': residue.name})
                continue
            selected.append({'id': f'p{len(selected)+1}',
                             'source': {'chain': chain.name, 'author_number': residue.seqid.num,
                                        'insertion_code': residue.seqid.icode.strip()},
                             'observed_sequence': info.one_letter_code,
                             'observed_coordinates': {a.name: list(a.pos) for a in residue}})
    return selected, excluded


def make_mpnn_fixture(source: Path, destination: Path):
    import gemmi
    structure = gemmi.read_structure(str(source))
    for chain in list(structure[0]):
        for i in range(len(chain) - 1, -1, -1):
            if chain.name != 'A' or not gemmi.find_tabulated_residue(chain[i].name).is_amino_acid():
                del chain[i]
    structure.write_pdb(str(destination))


def esm_stage(source: Path, output: Path):
    import numpy as np
    import torch
    from esm.pretrained import ESM3_structure_encoder_v0
    from esm.tokenization.sequence_tokenizer import EsmSequenceTokenizer
    from esm.tokenization.ss_tokenizer import SecondaryStructureTokenizer
    from esm.tokenization.sasa_tokenizer import SASADiscretizingTokenizer
    from esm.tokenization.structure_tokenizer import StructureTokenizer
    from esm.tokenization.function_tokenizer import InterProQuantizedTokenizer
    from esm.tokenization.residue_tokenizer import ResidueAnnotationsTokenizer
    from esm.utils import encoding
    from modules.esm3.adapters import ATOM37, protein_for
    from modules.esm3.contract import ESM3Request

    torch.set_num_threads(2)
    conditions = json.loads((output / 'edited-conditions.json').read_text())
    rows = conditions['positions']
    native_tracks = conditions['esm3_tracks']
    native = protein_for(ESM3Request('sequence', native_tracks), local=True)
    size = len(rows)
    check('edited length 56 + 3 - 1 = 58', size == 58)
    check('native ESMProtein coordinates shape', tuple(native.coordinates.shape) == (58, 37, 3))
    source_rows = json.loads((output / 'source-rows.json').read_text())
    original = {row['id']: row for row in source_rows}
    seed_positions = json.loads((output / 'conditions-bridge-input.json').read_text())['seed']['positions']
    original_conditions = {row['id']: row['condition'] for row in seed_positions}
    for i, row in enumerate(rows):
        if row['source'] is None:
            check(f'inserted {row["id"]} has no fabricated coordinates', torch.isnan(native.coordinates[i]).all())
        else:
            before = original[row['id']]
            check(f'{row["id"]} source identity preserved', row['source'] == before['source'])
            for atom, xyz in row['coordinate_condition'].items():
                check(f'{row["id"]}:{atom} atom content correspondence',
                      xyz == before['observed_coordinates'][atom] and np.allclose(native.coordinates[i, ATOM37.index(atom)].numpy(), xyz, atol=1e-6))
            check(f'{row["id"]} observed sequence retained', row['observed_sequence'] == before['observed_sequence'])
            check(f'{row["id"]} secondary condition follows source position', row['secondary_structure_condition'] == original_conditions[row['id']]['secondary'])
            check(f'{row["id"]} SASA condition follows source position', row['sasa_condition'] == original_conditions[row['id']]['sasa'])
    check('deleted source A25 absent', all(row['id'] != 'p25' for row in rows))
    check('sequence observations independent of masking',
          rows[5]['observed_sequence'] == original['p6']['observed_sequence'] and native.sequence[5] == '_')
    check('only selected backbone atoms used as conditions', torch.isnan(native.coordinates[:, ATOM37.index('CB')]).all())

    assets = source / '.models' / 'esm3'
    data = assets / 'data'
    seq_tokenizer = EsmSequenceTokenizer()
    ss_tokenizer = SecondaryStructureTokenizer(kind='ss8')
    sasa_tokenizer = SASADiscretizingTokenizer()
    structure_tokenizer = StructureTokenizer()
    function_tokenizer = InterProQuantizedTokenizer(
        lsh_path=data / 'hyperplanes_8bit_58641.npz',
        keyword_vocabulary_path=data / 'keyword_vocabulary_safety_filtered_58641.txt',
        keyword_idf_path=data / 'keyword_idf_safety_filtered_58641.npy',
        interpro_entry_path=data / 'entry_list_safety_29026.list',
        interpro2keywords_path=data / 'interpro_29026_to_keywords_58641.csv')
    residue_tokenizer = ResidueAnnotationsTokenizer(str(data / 'uniref90_and_mgnify90_residue_annotations_gt_1k_proteins.csv'))
    seq = encoding.tokenize_sequence(native.sequence, seq_tokenizer)
    ss = encoding.tokenize_secondary_structure(native.secondary_structure, ss_tokenizer)
    sasa = encoding.tokenize_sasa(native.sasa, sasa_tokenizer)
    function, residue = encoding.tokenize_function_annotations(native.function_annotations, native.sequence,
                                                               function_tokenizer, residue_tokenizer)
    from esm.utils.types import FunctionAnnotation
    expect_rejection('native function tokenizer rejects unsupported labels',
                     lambda: encoding.tokenize_function_annotations([FunctionAnnotation('binding', 1, 1)], native.sequence,
                                                                      function_tokenizer, residue_tokenizer),
                     'Unknown label')
    for name, tensor in [('sequence', seq), ('secondary_structure', ss), ('sasa', sasa),
                         ('function', function), ('residue_annotations', residue)]:
        check(name + ' native token length includes BOS/EOS', tensor.shape[0] == size + 2, shape=list(tensor.shape))
    for i, row in enumerate(rows):
        expected = seq_tokenizer.mask_token_id if row['sequence_condition'] is None else seq_tokenizer.encode(row['sequence_condition'], add_special_tokens=False)[0]
        check(f'{row["id"]} sequence token maps to current index + 1', int(seq[i + 1]) == expected)
        check(f'{row["id"]} secondary token maps to current index + 1',
              int(ss[i + 1]) == int(encoding.tokenize_secondary_structure(native.secondary_structure[i], ss_tokenizer, False)[0]))
        check(f'{row["id"]} SASA token maps to current index + 1',
              int(sasa[i + 1]) == int(encoding.tokenize_sasa([native.sasa[i]], sasa_tokenizer, False)[0]))
    annotated = {i for interval in native.function_annotations for i in range(interval.start - 1, interval.end)}
    check('function interval members survive insertion without expanding',
          {rows[i]['id'] for i in annotated} == {'p10', 'p11', 'p12', 'p13'})
    for i, row in enumerate(rows):
        expected_active = row['id'] in {'p10', 'p11', 'p12', 'p13'}
        check(f'{row["id"]} function token content correspondence',
              bool((function[i + 1] != function_tokenizer.vocab_to_index['<none>']).any()) == expected_active)
    check('sequence special tokens are native BOS/EOS', int(seq[0]) == seq_tokenizer.bos_token_id and int(seq[-1]) == seq_tokenizer.eos_token_id)

    # Upstream's documented local-provider branch uses cwd as its data root.
    # This dedicated supervised child is the only process whose cwd/environment changes.
    os.environ['INFRA_PROVIDER'] = 'prototype-local-assets'
    os.chdir(assets)
    encoder = ESM3_structure_encoder_v0('cpu')
    with torch.inference_mode():
        encoded_coords, plddt, struct_tokens = encoding.tokenize_structure(native.coordinates, encoder, structure_tokenizer,
                                                                         reference_sequence=native.sequence)
    check('learned structure encoder returns length + 2 tokens', tuple(struct_tokens.shape) == (60,))
    check('structure tokens native BOS/EOS', int(struct_tokens[0]) == structure_tokenizer.bos_token_id and int(struct_tokens[-1]) == structure_tokenizer.eos_token_id)
    check('structure encoding preserves coordinate order and missing values',
          torch.allclose(encoded_coords[1:-1], native.coordinates, equal_nan=True))
    check('structure coordinate special tokens padded with infinity', torch.isinf(encoded_coords[[0, -1]]).all())
    missing_tokens = [int(struct_tokens[i + 1]) for i, row in enumerate(rows) if row['source'] is None]
    check('native missing-coordinate positions receive codebook tokens, not structure masks',
          len(missing_tokens) == 3 and all(token != structure_tokenizer.mask_token_id for token in missing_tokens),
          actual_tokens=missing_tokens, mask_token_id=structure_tokenizer.mask_token_id)
    from esm.sdk.api import GenerationConfig
    check('native GenerationConfig defaults to coordinate-only conditioning', GenerationConfig(track='sequence').condition_on_coordinates_only is True)
    np.savez_compressed(output / 'esm3-arrays.npz', raw_coordinates=native.coordinates.numpy(),
                        encoded_coordinates=encoded_coords.numpy(), structure_tokens=struct_tokens.numpy(),
                        sequence_tokens=seq.numpy(), secondary_structure_tokens=ss.numpy(),
                        sasa_tokens=sasa.numpy(), function_tokens=function.numpy(), residue_tokens=residue.numpy())
    write(output / 'esm3-tokens.json', {'current_positions': [row['id'] for row in rows],
                                      'sequence': seq.tolist(), 'secondary_structure': ss.tolist(), 'sasa': sasa.tolist(),
                                      'function': function.tolist(), 'residue_annotations': residue.tolist(),
                                      'structure': struct_tokens.tolist(),
                                      'missing_structure_token_ids': missing_tokens,
                                      'structure_mask_token_id': structure_tokenizer.mask_token_id})
    write(output / 'esm3-evidence.json', {'executed': 'real pinned native ESMProtein, tokenizers, and learned structure encoder checkpoint',
                                       'sequence_generation_executed': False,
                                       'structure_generation_executed': False,
                                       'synthetic_condition_tracks': ['secondary_structure', 'sasa', 'function_annotations'],
                                       'synthetic_condition_note': 'Test conditions exercise correspondence; these are not biological annotations measured for 1PGA.',
                                       'open_seam': {'observation': 'Missing coordinates yielded codebook tokens instead of mask tokens. The native encoder output is preserved unchanged.',
                                                     'actual_missing_tokens': missing_tokens, 'native_mask_id': structure_tokenizer.mask_token_id,
                                                     'source_inspection': {'file': 'repositories/esm/esm/utils/generation.py', 'lines': [368, 369],
                                                                           'behavior': 'With condition_on_coordinates_only=True and coordinates present, iterative sampling clears the entire structure token track before generation.'},
                                                     'not_yet_validated': 'Full generation with partial coordinates, for both coordinate-only settings, and its scientifically intended masking behavior.'},
                                       'checks': CHECKS})


def mpnn_stage(source: Path, output: Path):
    import gemmi
    from modules.proteinmpnn.adapters import create_local, prepare_structure
    from modules.proteinmpnn.contract import MPNNRequest

    folder = output / 'proteinmpnn'
    folder.mkdir(exist_ok=True)
    make_mpnn_fixture(HERE / 'fixtures' / '1PGA.pdb', folder / 'protein-chain-A.pdb')
    runtime = SimpleNamespace(workdir=folder, cancelled=False)
    settings = {'python': sys.executable, 'source': str(source / 'repositories' / 'ProteinMPNN'),
                'weights': str(source / '.models' / 'proteinmpnn'), 'device': 'cpu'}
    tool = create_local(settings)
    design_parameters = {'seed': 42, 'num_seq_per_target': 2, 'batch_size': 1,
                         'sampling_temp': [0.1], 'fixed_positions': {'A': [1, 2, 3, 4, 5]}}
    request = MPNNRequest('protein-chain-A.pdb', 'pdb')
    result = tool(request, design_parameters, runtime)
    write(folder / 'design.json', asdict(result))
    check('real ProteinMPNN returns two requested candidates', len(result.samples) == 2)
    for i, sample in enumerate(result.samples):
        check(f'candidate {i+1} chain length and fixed residues', len(sample['chains']['A']) == 56 and sample['chains']['A'][:5] == 'MTYKL')
        check(f'candidate {i+1} actual per-residue scores', len(sample['residue_nll']['A']) == 56)
        check(f'candidate {i+1} native mask honors fixed positions', sample['design_mask']['A'][:5] == [0.] * 5 and sample['design_mask']['A'][5:] == [1.] * 51)
    independent_parameters = {'seed': 43, 'num_seq_per_target': 1, 'batch_size': 1}
    selected = result.samples[0]['chains']
    score_request = MPNNRequest('protein-chain-A.pdb', 'pdb', sequences=selected)
    score = tool(score_request, independent_parameters, runtime)
    write(folder / 'independent-score.json', asdict(score))
    check('same shared tool performs independent score-only operation', len(score.samples) == 1 and score.samples[0]['temperature'] is None)
    check('independent scoring uses supplied candidate unchanged', score.samples[0]['chains'] == selected)
    check('independent score covers all explicitly requested positions', score.samples[0]['design_mask']['A'] == [1.] * 56)
    expect_rejection('actual MPNN adapter rejects length-changing score without matching backbone',
                     lambda: tool(MPNNRequest('protein-chain-A.pdb', 'pdb', {'A': selected['A'] + 'GG'}), independent_parameters, runtime),
                     'complete chain sequence correspondence')
    broken = gemmi.read_structure(str(folder / 'protein-chain-A.pdb'))
    residue = broken[0]['A'][10]
    residue.remove_atom('O', '*')
    broken.write_pdb(str(folder / 'incomplete-backbone.pdb'))
    expect_rejection('actual MPNN adapter rejects an incomplete backbone',
                     lambda: prepare_structure(MPNNRequest('incomplete-backbone.pdb', 'pdb'), folder),
                     'unambiguous O atom')
    edited = json.loads((output / 'edited-conditions.json').read_text())['positions']
    def require_complete_backbone():
        for row in edited:
            coords = row['coordinate_condition']
            if coords is None or any(atom not in coords for atom in ('N', 'CA', 'C', 'O')):
                raise ValueError(f'Backbone design requires complete N/CA/C/O at every current position; missing at {row["id"]}')
    expect_rejection('operation refuses edited incomplete conditions before ProteinMPNN call',
                     require_complete_backbone, 'complete N/CA/C/O')
    write(folder / 'request-config.json', {'settings': settings, 'design': design_parameters, 'independent_score': independent_parameters,
                                          'fixed_position_semantics': 'native one-based chain order; A1-5 explicit here',
                                          'selection': 'canonical protein residues of chain A; original complete PDB retained in fixtures',
                                          'score_semantics': {'design': 'NLL on design_mask (positions 6-56)', 'independent': 'NLL on all 56 positions; new seed and decoding order'}})
    write(output / 'proteinmpnn-evidence.json', {'executed': 'real CPU ProteinMPNN sampling and independent model score pass', 'checks': CHECKS})


def tool_boundary_stage(output: Path):
    import numpy as np
    import torch
    from esm.sdk.api import ESMProtein, GenerationConfig
    from esm.tokenization.sequence_tokenizer import EsmSequenceTokenizer
    from esm.tokenization.ss_tokenizer import SecondaryStructureTokenizer
    from esm.tokenization.sasa_tokenizer import SASADiscretizingTokenizer
    from esm.utils import encoding

    subprocess.run(['node', str(HERE / 'tool-boundary-bridge.cjs'), str(output / 'edited-conditions.json'),
                    str(output / 'tool-boundary-compiled.json')], check=True)
    exported = json.loads((output / 'tool-boundary-compiled.json').read_text())
    compiled = exported['compiled']
    values = compiled['payload']['protein']
    values['coordinates'] = torch.from_numpy(np.asarray(values['coordinates'], dtype=np.float32))
    native = ESMProtein(**values)
    config = GenerationConfig(**compiled['payload']['generation'])
    existing = np.load(output / 'esm3-arrays.npz')
    seq = encoding.tokenize_sequence(native.sequence, EsmSequenceTokenizer())
    ss = encoding.tokenize_secondary_structure(native.secondary_structure, SecondaryStructureTokenizer(kind='ss8'))
    sasa = encoding.tokenize_sasa(native.sasa, SASADiscretizingTokenizer())
    check('actual HTML compiler coordinates match conditions-to-adapter path', np.allclose(native.coordinates.numpy(), existing['raw_coordinates'], equal_nan=True))
    check('actual HTML compiler sequence tokens match conditions-to-adapter path', np.array_equal(seq.numpy(), existing['sequence_tokens']))
    check('actual HTML compiler secondary tokens match conditions-to-adapter path', np.array_equal(ss.numpy(), existing['secondary_structure_tokens']))
    check('actual HTML compiler SASA tokens match conditions-to-adapter path', np.array_equal(sasa.numpy(), existing['sasa_tokens']))
    positions = json.loads((output / 'edited-conditions.json').read_text())['positions']
    check('actual HTML compiler binding preserves current positions', compiled['binding']['keys'] == [row['id'] for row in positions])
    check('actual HTML compiler config accepted by pinned GenerationConfig', config.track == 'sequence' and config.num_steps == 8 and config.temperature == 0.7)
    write(output / 'tool-boundary-evidence.json', {'executed': 'actual tool-boundary HTML compiler into pinned ESMProtein, GenerationConfig, and sequence/SS/SASA tokenizers',
                                                'generation_executed': False, 'checks': CHECKS})


def compare_operation(subject, reference, tool, tool_parameters):
    """One operation, injected implementation, unchanged input/output envelope."""
    return {'subject': subject['id'], 'reference': reference['id'],
            **tool(subject, reference, tool_parameters)}


def kabsch_tool(subject, reference, parameters):
    import numpy as np
    pairs = parameters['pairs']
    x = np.asarray([subject['coordinates'][i] for i, _ in pairs])
    y = np.asarray([reference['coordinates'][j] for _, j in pairs])
    xc, yc = x.mean(0), y.mean(0)
    u, _, vt = np.linalg.svd((x - xc).T @ (y - yc))
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    row_rotation = u @ correction @ vt
    translation = yc - xc @ row_rotation
    rmsd = float(np.sqrt(np.mean(np.sum((x @ row_rotation + translation - y) ** 2, axis=1))))
    return {'method': 'NumPy Kabsch least-squares rigid fit', 'correspondence': 'explicit supplied C-alpha index pairs',
            'pairs': pairs, 'metrics': {'rmsd': {'value': rmsd, 'unit': 'angstrom', 'scope': 'all explicitly paired C-alpha atoms'}},
            'transform': {'convention': 'row: x @ rotation.T + translation', 'rotation': row_rotation.T.tolist(), 'translation': translation.tolist()}}


def tmalign_tool(subject, reference, parameters):
    import numpy as np
    from tmtools import tm_align
    if parameters:
        raise ValueError('This TM-align prototype accepts no extra tool parameters')
    x, y = np.asarray(subject['coordinates']), np.asarray(reference['coordinates'])
    result = tm_align(x, y, subject['sequence'], reference['sequence'])
    pairs, i, j = [], 0, 0
    for a, b in zip(result.seqxA, result.seqyA, strict=True):
        if a != '-' and b != '-':
            pairs.append([i, j])
        i += a != '-'
        j += b != '-'
    return {'method': 'TM-align via tmtools 0.3.0', 'correspondence': 'TM-align inferred structural alignment',
            'pairs': pairs, 'aligned_sequences': [result.seqxA, result.seqyA],
            'metrics': {'rmsd': {'value': float(result.rmsd), 'unit': 'angstrom', 'scope': 'TM-align aligned C-alpha pairs'},
                        'tm_subject': {'value': float(result.tm_norm_chain1), 'normalization_length': len(x)},
                        'tm_reference': {'value': float(result.tm_norm_chain2), 'normalization_length': len(y)}},
            'transform': {'convention': 'row: x @ rotation.T + translation', 'rotation': result.u.tolist(), 'translation': result.t.tolist()}}


def comparison_stage(output: Path):
    import numpy as np
    rows = json.loads((output / 'source-rows.json').read_text())
    xyz = np.asarray([row['observed_coordinates']['CA'] for row in rows])
    reference = {'id': '1PGA-chain-A', 'sequence': ''.join(row['observed_sequence'] for row in rows),
                 'positions': [row['source'] for row in rows], 'coordinates': xyz.tolist()}
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    translation = np.array([10., 20., -5.])
    subject = {**deepcopy(reference), 'id': '1PGA-rigid-transformed', 'coordinates': (xyz @ rotation.T + translation).tolist()}
    results = []
    for tool, parameters in [(kabsch_tool, {'pairs': [[i, i] for i in range(56)]}), (tmalign_tool, {})]:
        result = compare_operation(subject, reference, tool, parameters)
        check(result['method'] + ' rigid-transform RMSD near zero', result['metrics']['rmsd']['value'] < 1e-5)
        check(result['method'] + ' paired all residues', len(result['pairs']) == 56)
        results.append(result)
    check('Kabsch does not fabricate optional TM-score', 'tm_subject' not in results[0]['metrics'])
    check('TM-align emits actual optional normalized TM-scores', abs(results[1]['metrics']['tm_subject']['value'] - 1) < 1e-6)
    shortened = {**subject, 'id': '1PGA-rigid-transformed-delete-A25',
                 'sequence': subject['sequence'][:24] + subject['sequence'][25:],
                 'positions': subject['positions'][:24] + subject['positions'][25:],
                 'coordinates': subject['coordinates'][:24] + subject['coordinates'][25:]}
    explicit_pairs = [[i, i if i < 24 else i + 1] for i in range(55)]
    for tool, parameters in [(kabsch_tool, {'pairs': explicit_pairs}), (tmalign_tool, {})]:
        result = compare_operation(shortened, reference, tool, parameters)
        check(result['method'] + ' handles 55 vs 56 residues', len(result['pairs']) == 55 and result['metrics']['rmsd']['value'] < 1e-5)
        results.append(result)
    expect_rejection('TM-align rejects unsupported explicit-mapping option rather than ignoring it',
                     lambda: compare_operation(subject, reference, tmalign_tool, {'pairs': [[0, 0]]}), 'no extra tool parameters')
    write(output / 'comparison-inputs.json', {'reference': reference, 'rigid_subject': subject, 'deleted_residue_subject': shortened})
    write(output / 'comparison-results.json', results)
    write(output / 'comparison-evidence.json', {'executed': 'real NumPy SVD Kabsch and native TM-align through one prototype comparison operation',
                                             'caveat': 'Kabsch optimizes supplied pairs; TM-align determines structural correspondence. RMSD scope remains explicit. No interchangeable scientific scores are assumed.',
                                             'checks': CHECKS})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=['all', 'esm', 'mpnn', 'comparison', 'tool-boundary', 'summary'], default='all')
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output.resolve()
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / 'repositories' / 'esm'))
    output.mkdir(parents=True, exist_ok=True)
    if args.stage == 'esm':
        esm_stage(source, output)
    elif args.stage == 'mpnn':
        mpnn_stage(source, output)
    elif args.stage == 'comparison':
        comparison_stage(output)
    elif args.stage == 'tool-boundary':
        tool_boundary_stage(output)
    elif args.stage == 'summary':
        summarize(source, output)
    else:
        run_all(source, output)


def run_all(source, output):
    # The actual portable conditions prototype writes edited-conditions.json.
    # See bridge invocation populated below; this runner never independently replays its edits.
    from protein_workbench_public.worker_process import run_worker
    write(output / 'summary.json', {'status': 'running'})
    rows, excluded = load_rows(HERE / 'fixtures' / '1PGA.pdb')
    write(output / 'source-rows.json', rows)
    write(output / 'explicit-input-selection.json', {'selected': 'canonical protein chain A', 'excluded': excluded})
    bridge_export(source, output, rows)
    command = [sys.executable, str(Path(__file__).resolve()), '--source-root', str(source), '--output', str(output)]
    run_worker(command + ['--stage', 'esm'], cwd=source, log_path=output / 'esm3-worker.log', cancelled=lambda: False, label='Prototype ESM3 structure encoder')
    subprocess.run(command + ['--stage', 'mpnn'], cwd=source, check=True)
    subprocess.run(command + ['--stage', 'comparison'], cwd=source, check=True)
    subprocess.run(command + ['--stage', 'tool-boundary'], cwd=source, check=True)
    summarize(source, output)


def summarize(source, output):
    reports = {name: json.loads((output / (name + '-evidence.json')).read_text()) for name in ['esm3', 'proteinmpnn', 'comparison', 'tool-boundary']}
    count = sum(len(report['checks']) for report in reports.values())
    write(output / 'summary.json', {'status': 'passed', 'checks': count, 'bridge_checks': 1, 'total_checks': count + 1,
                                  'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip(),
                                  'reports': {name: {'executed': report['executed'], 'checks': len(report['checks'])} for name, report in reports.items()},
                                  'not_executed': ['full ESM3 sequence generation', 'ESM3 structure generation', 'folding candidate sequences', 'application end-to-end loop'],
                                  'verdicts': ['Conditions need explicit ordered positions and edit-owned correspondence.',
                                               'Native encoding and masks remain model adapter responsibility.',
                                               'ProteinMPNN design and independent scoring can share a tool implementation with separate task scope.',
                                               'Comparison tool replacement works only with explicit method, mapping policy, scope, and optional outputs.'],
                                  'open_seams': [reports['esm3']['open_seam']]})
    print(json.dumps({'status': 'passed', 'checks': count, 'output': str(output)}))


def bridge_export(source, output, rows):
    positions = []
    for index, row in enumerate(rows):
        positions.append({'id': row['id'], 'residue': row['observed_sequence'],
                          'source': {'objectId': '1PGA-chain-A', 'chain': row['source']['chain'],
                                     'authorNumber': row['source']['author_number'], 'insertionCode': row['source']['insertion_code']},
                          'observed': {'residue': row['observed_sequence'],
                                       'coordinates': {'frame': '1PGA-frame', 'atoms': row['observed_coordinates']},
                                       'secondary': None, 'sasa': None},
                          'condition': {'sequence': row['observed_sequence'] if index < 5 else None,
                                        'coordinates': {'frame': '1PGA-frame', 'atoms': {name: row['observed_coordinates'][name] for name in ('N', 'CA', 'C', 'O')}},
                                        'secondary': 'H' if index % 2 else 'E', 'sasa': float(index)}})
    bridge_input = {'seed': {'objectId': '1PGA-chain-A', 'positions': positions,
                             'regions': [{'id': 'membership-function-condition', 'members': ['p10', 'p11', 'p12', 'p13']}], 'pairs': []},
                    'actions': [{'type': 'insert', 'after': 'p11', 'residue': 'G'}] * 3 + [{'type': 'delete', 'id': 'p25'}]}
    write(output / 'conditions-bridge-input.json', bridge_input)
    bridge = HERE.parents[1] / 'sequence_edit' / 'prototype_conditions' / 'export.cjs'
    with (output / 'conditions-bridge.log').open('w') as log:
        subprocess.run(['node', str(bridge), str(output / 'conditions-bridge-input.json'), str(output / 'conditions-bridge-output.json')],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    exported = json.loads((output / 'conditions-bridge-output.json').read_text())
    check('both actual JavaScript representations export identical real-structure conditions', exported['representationsEqual'])
    public = exported['request']
    normalized = []
    for row in public['positions']:
        origin, observed, condition = row['source'], row['observed'], row['condition']
        normalized.append({'id': row['id'], 'source': None if origin is None else {'chain': origin['chain'], 'author_number': origin['authorNumber'], 'insertion_code': origin['insertionCode']},
                           'observed_sequence': None if observed is None else observed['residue'],
                           'sequence_condition': condition['sequence'],
                           'coordinate_condition': None if condition['coordinates'] is None else condition['coordinates']['atoms'],
                           'secondary_structure_condition': condition['secondary'], 'sasa_condition': condition['sasa']})
    # Membership semantics compile into multiple native contiguous intervals when necessary.
    member_ids = set(public['regions'][0]['members'])
    intervals = []
    for index, row in enumerate(normalized, start=1):
        if row['id'] in member_ids:
            if intervals and intervals[-1]['end'] == index - 1:
                intervals[-1]['end'] = index
            else:
                intervals.append({'label': 'immunoglobulin binding', 'start': index, 'end': index})
    tracks = {'sequence': ''.join(row['sequence_condition'] or '_' for row in normalized),
              'coordinates': [row['coordinate_condition'] for row in normalized],
              'secondary_structure': ''.join(row['secondary_structure_condition'] or '_' for row in normalized),
              'sasa': [row['sasa_condition'] for row in normalized], 'function_annotations': intervals}
    write(output / 'edited-conditions.json', {'positions': normalized, 'esm3_tracks': tracks})
    write(output / 'bridge-evidence.json', {'checks': CHECKS})


if __name__ == '__main__':
    main()
