"""THROWAWAY: standard structure file plus a small explicit editing request.

Actual ESM SDK parsing/encoding and pretrained native ESM3 sequence generation.
The public request contains no atom37 arrays. Conversion belongs to this adapter.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
CHECKS = []


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def check(name, passed, **detail):
    CHECKS.append({'check': name, 'passed': bool(passed), **detail})
    if not passed:
        raise AssertionError(name)


def compile_request(request, fixture_dir):
    """This adapter reads explicit source identities; no sequence-alignment guess."""
    import gemmi
    import numpy as np
    import torch
    from esm.sdk.api import ESMProtein
    from esm.utils.structure.protein_chain import ProteinChain
    from esm.utils import residue_constants

    path = fixture_dir / request['structure_file']
    if Path(request['structure_file']).name != request['structure_file']:
        raise ValueError('Fixture file must be a package-local basename')
    structure = gemmi.read_structure(str(path))
    if len(structure) != 1:
        raise ValueError('Select one model before this single-model prototype operation')
    chain = ProteinChain.from_pdb(path, chain_id=request['chain'])
    identities = [(int(number), str(code)) for number, code in zip(chain.residue_index, chain.insertion_code)]
    if len(identities) != len(set(identities)):
        raise ValueError('Source residue identities are ambiguous')
    lookup = {key: i for i, key in enumerate(identities)}
    mapping = request['target_to_source']
    if not mapping:
        raise ValueError('Target must contain at least one position')
    source_indexes = []
    for source in mapping:
        if source is None:
            source_indexes.append(None)
        else:
            key = (source['author_number'], source['insertion_code'])
            if key not in lookup:
                raise ValueError(f'Source residue does not exist: {key}')
            source_indexes.append(lookup[key])
    sequence = ['_'] * len(mapping)
    coordinates = np.full((len(mapping), 37, 3), np.nan, dtype=np.float32)
    used_sequence = set()
    used_coordinates = set()
    for item in request['sequence_conditions']:
        index, aa = item['target_index'], item['amino_acid']
        if type(index) is not int or not 0 <= index < len(mapping) or index in used_sequence:
            raise ValueError('Sequence condition requires one valid target index')
        if len(aa) != 1 or aa not in 'ACDEFGHIKLMNPQRSTVWY':
            raise ValueError('Sequence condition requires one canonical amino acid')
        sequence[index] = aa
        used_sequence.add(index)
    for item in request['coordinate_conditions']:
        index = item['target_index']
        if type(index) is not int or not 0 <= index < len(mapping):
            raise ValueError('Coordinate condition requires a valid target index')
        if source_indexes[index] is None:
            raise ValueError('Inserted position has no source coordinates')
        if sorted(item['atoms']) != ['C', 'CA', 'N']:
            raise ValueError('This ESM coordinate-condition operation requires the complete N/CA/C backbone frame')
        for atom in item['atoms']:
            if atom not in residue_constants.atom_order or (index, atom) in used_coordinates:
                raise ValueError('Coordinate atom unsupported or repeated')
            atom_index = residue_constants.atom_order[atom]
            xyz = chain.atom37_positions[source_indexes[index], atom_index]
            if not np.isfinite(xyz).all():
                raise ValueError(f'Selected coordinate absent: target {index}, atom {atom}')
            coordinates[index, atom_index] = xyz
            used_coordinates.add((index, atom))
    return ESMProtein(sequence=''.join(sequence), coordinates=torch.tensor(coordinates)), chain, source_indexes


def rejected(name, callback):
    try:
        callback()
    except ValueError as error:
        check(name, True, diagnostic=str(error))
    else:
        check(name, False)


def preparation(request, output):
    import gemmi
    import numpy as np
    import torch
    from esm.sdk.api import ESMProtein
    from esm.utils import residue_constants

    protein, chain, source_indexes = compile_request(request, HERE / 'fixtures')
    raw = ESMProtein.from_pdb(HERE / 'fixtures' / '1PGA.pdb', chain_id='A')
    check('file-only import contains 56 observed residues and no sequence masks', len(raw.sequence) == 56 and '_' not in raw.sequence)
    check('target mapping creates 58 positions', len(protein.sequence) == 58)
    check('inserted positions have no fabricated coordinates', torch.isnan(protein.coordinates[11:14]).all())
    check('deleted source A25 is absent', all(row is None or row['author_number'] != 25 for row in request['target_to_source']))
    check('only five selected sequence letters become fixed', protein.sequence == 'MTYKL' + '_' * 53)
    check('all mapped target positions receive chosen three backbone atoms', int(torch.isfinite(protein.coordinates).all(-1).sum()) == 55 * 3)
    for i, source_index in enumerate(source_indexes):
        if source_index is not None:
            check(f'target {i} retains exact source backbone coordinates', np.allclose(protein.coordinates[i, :3].numpy(), chain.atom37_positions[source_index, :3]))
    sparse = deepcopy(request)
    sparse['coordinate_conditions'] = [item for item in sparse['coordinate_conditions'] if item['target_index'] < 5]
    sparse_protein, _, _ = compile_request(sparse, HERE / 'fixtures')
    check('coordinate selection changes without changing sequence conditions', sparse_protein.sequence == protein.sequence and int(torch.isfinite(sparse_protein.coordinates).all(-1).sum()) == 15)
    independent = deepcopy(sparse)
    independent['sequence_conditions'] = [{'target_index': 5, 'amino_acid': 'A'}]
    independent_protein, _, _ = compile_request(independent, HERE / 'fixtures')
    check('sequence selection changes without changing coordinate conditions', torch.allclose(independent_protein.coordinates, sparse_protein.coordinates, equal_nan=True) and independent_protein.sequence == '_____' + 'A' + '_' * 52)

    # A standard PDB produced by a naive 'just write the selected coordinates'
    # path has no ATOM rows for new residues. Native from_pdb reads its 55 rows,
    # even if the remaining author numbers contain the three target gaps.
    structure = gemmi.Structure()
    model = gemmi.Model('1')
    new_chain = gemmi.Chain('A')
    original = gemmi.read_structure(str(HERE / 'fixtures' / '1PGA.pdb'))[0]['A']
    residue_lookup = {(res.seqid.num, res.seqid.icode.strip()): res for res in original}
    for i, mapped in enumerate(request['target_to_source']):
        if mapped is None:
            continue
        residue = residue_lookup[(mapped['author_number'], mapped['insertion_code'])].clone()
        residue.seqid = gemmi.SeqId(i + 1, ' ')
        new_chain.add_residue(residue)
    model.add_chain(new_chain)
    structure.add_model(model)
    structure.write_pdb(str(output / 'edited-observed-only.pdb'))
    lossy = ESMProtein.from_pdb(output / 'edited-observed-only.pdb', chain_id='A')
    check('naive atom-only edited PDB is reimported as 55 positions, losing three target slots', len(lossy.sequence) == 55, reimported_sequence=lossy.sequence)
    bad = deepcopy(request)
    bad['coordinate_conditions'].append({'target_index': 11, 'atoms': ['CA']})
    rejected('new position cannot pretend it has source coordinates', lambda: compile_request(bad, HERE / 'fixtures'))
    bad = deepcopy(request)
    bad['target_to_source'][0]['author_number'] = 999
    rejected('missing source identity is refused instead of guessed', lambda: compile_request(bad, HERE / 'fixtures'))
    np.savez_compressed(output / 'compiled-inputs.npz', coordinates=protein.coordinates.numpy(), sparse_coordinates=sparse_protein.coordinates.numpy())
    write(output / 'request.json', request)
    write(output / 'sparse-request.json', sparse)
    write(output / 'preparation.json', {'status': 'passed', 'indexing': 'target_index is zero-based; source numbers are PDB author numbers', 'source_sequence': raw.sequence, 'native_sequence_prompt': protein.sequence, 'checks': CHECKS})
    return protein, sparse_protein


def inspect_boundary(request, output):
    import torch
    from esm.sdk.api import ESMProtein
    from esm.utils.structure.affine3d import build_affine3d_from_coordinates
    from esm.utils.structure.protein_chain import ProteinChain

    start = len(CHECKS)
    protein, _, _ = compile_request(request, HERE / 'fixtures')
    full = protein.coordinates[:, :3].unsqueeze(0)
    ca_only = full.clone()
    ca_only[:, :, 0] = float('nan')
    ca_only[:, :, 2] = float('nan')
    _, full_mask = build_affine3d_from_coordinates(full)
    _, ca_only_mask = build_affine3d_from_coordinates(ca_only)
    check('native geometric conditioning sees 55 complete backbone frames', int(full_mask.sum()) == 55)
    check('CA-only coordinates provide zero native geometric frames', int(ca_only_mask.sum()) == 0)
    ca_request = deepcopy(request)
    ca_request['coordinate_conditions'] = [{'target_index': 0, 'atoms': ['CA']}]
    rejected('adapter refuses a CA-only condition that cannot form native geometry', lambda: compile_request(ca_request, HERE / 'fixtures'))
    for atoms in [['O'], ['N', 'CA', 'C', 'CA']]:
        unsupported = deepcopy(request)
        unsupported['coordinate_conditions'] = [{'target_index': 0, 'atoms': atoms}]
        rejected(f'adapter refuses unsupported or duplicate coordinate selection {atoms}', lambda: compile_request(unsupported, HERE / 'fixtures'))
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(prefix='PROTOTYPE-independent-esm-bundle-') as scratch:
        bundle = Path(scratch)
        shutil.copyfile(HERE / 'fixtures' / request['structure_file'], bundle / request['structure_file'])
        write(bundle / 'request.json', request)
        independent, _, _ = compile_request(json.loads((bundle / 'request.json').read_text()), bundle)
        check('copied standalone file and request reproduce native input without producer paths', independent.sequence == protein.sequence and torch.allclose(independent.coordinates, protein.coordinates, equal_nan=True))
    raw = ESMProtein.from_pdb(HERE / 'fixtures' / '1PGA.pdb', chain_id='A')
    check('native ESMProtein convenience import does not retain residue identity field', raw.residue_index is None)
    try:
        ProteinChain.from_atom37(raw.coordinates, sequence='_' * 58)
    except (AssertionError, ValueError) as error:
        check('native structure conversion refuses 58 sequence with 56 coordinate rows', True, error_type=type(error).__name__, diagnostic=str(error))
    else:
        check('native structure conversion refuses 58 sequence with 56 coordinate rows', False)
    write(output / 'boundary-findings.json', {'executed': 'actual native ESM parsing, ProteinChain conversion and geometric-frame construction; no model weights needed', 'checks': CHECKS[start:]})


def generation(source, output, protein, sparse_protein):
    import attr
    import numpy as np
    import psutil
    import torch
    from accelerate import init_empty_weights
    from esm.models.esm3 import ESM3
    from esm.pretrained import ESM3_structure_encoder_v0, ESM3_structure_decoder_v0, ESM3_function_decoder_v0
    from esm.tokenization import get_esm3_model_tokenizers
    from esm.utils.constants.models import ESM3_OPEN_SMALL
    from esm.sdk.api import ESMProteinError, GenerationConfig

    os.environ['INFRA_PROVIDER'] = 'prototype-local-assets'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['DISABLE_ITERATIVE_SAMPLING_TQDM'] = '1'
    os.chdir(source / '.models' / 'esm3')
    torch.set_num_threads(2)
    started = time.monotonic()
    memory_before = psutil.virtual_memory()._asdict()
    print('Loading mmap float32 ESM3 weights on CPU; native tensor generation avoids unrelated decoders', flush=True)
    # Same constructor parameters as the pinned ESM3_sm_open_v0 builder.
    # Read-only mmap avoids eagerly allocating the entire 2.8 GB checkpoint.
    with init_empty_weights():
        model = ESM3(d_model=1536, n_heads=24, v_heads=256, n_layers=48,
                     structure_encoder_fn=ESM3_structure_encoder_v0,
                     structure_decoder_fn=ESM3_structure_decoder_v0,
                     function_decoder_fn=ESM3_function_decoder_v0,
                     tokenizers=get_esm3_model_tokenizers(ESM3_OPEN_SMALL)).eval()
    state = torch.load('data/weights/esm3_sm_open_v1.pth', map_location='cpu', mmap=True, weights_only=True)
    # The CPU geometric-attention path requires float32. Convert one tensor at
    # a time into an anonymous scratch mapping instead of allocating 5.6 GB RAM.
    import tempfile
    descriptor, scratch = tempfile.mkstemp(prefix='PROTOTYPE-esm3-fp32-', suffix='.weights', dir='/private/tmp')
    os.close(descriptor)
    element_count = sum(tensor.numel() for tensor in state.values())
    mapped = np.memmap(scratch, dtype=np.float32, mode='w+', shape=(element_count,))
    os.unlink(scratch)  # Mapping stays live; the OS releases scratch space on exit.
    converted = {}
    offset = 0
    for key, tensor in state.items():
        end = offset + tensor.numel()
        mapped[offset:end] = tensor.float().reshape(-1).numpy()
        converted[key] = torch.from_numpy(mapped[offset:end].reshape(tuple(tensor.shape)))
        offset = end
        mapped.flush()
    model.load_state_dict(converted, assign=True, strict=True)
    del state, converted
    print('Model loaded', time.monotonic() - started, flush=True)
    with torch.inference_mode():
        tokens = model.encode(protein)
        sparse_tokens = model.encode(sparse_protein)
    mask_id = model.tokenizers.structure.mask_token_id
    missing_tokens = tokens.structure[12:15].tolist()
    check('learned encoder gives a codebook token to absent coordinates', all(value != mask_id for value in missing_tokens), actual=missing_tokens, native_mask_id=mask_id)
    reports = []
    arrays = {}
    current_capture = {}

    def observe_input(_module, args, kwargs):
        current_capture['structure_tokens'] = kwargs['structure_tokens'].detach().cpu().clone()
        current_capture['sequence_tokens'] = kwargs['sequence_tokens'].detach().cpu().clone()
        current_capture['coordinates'] = kwargs['structure_coords'].detach().cpu().clone()

    def observe_output(_module, args, result):
        current_capture['sequence_logits'] = result.sequence_logits.detach().float().cpu().clone()

    pre_hook = model.register_forward_pre_hook(observe_input, with_kwargs=True)
    post_hook = model.register_forward_hook(observe_output)
    # Same seed and task; only the specified native conditioning choice differs.
    configurations = [('all_coords_default_true', tokens, True), ('all_coords_false', tokens, False), ('sparse_coords_default_true', sparse_tokens, True)]
    for name, input_tokens, coordinate_only in configurations:
        current_capture.clear()
        config = GenerationConfig(track='sequence', num_steps=1, temperature=0.5, temperature_annealing=False, condition_on_coordinates_only=coordinate_only)
        torch.manual_seed(42)
        case_start = time.monotonic()
        with torch.inference_mode():
            result = model.generate(attr.evolve(input_tokens), config)
        if isinstance(result, ESMProteinError):
            raise RuntimeError(f'{name}: {result.error_code} {result.error_msg}')
        sequence = model.tokenizers.sequence.decode(result.sequence[1:-1].tolist()).replace(' ', '')
        check(name + ' real native generation fills all target positions', len(sequence) == 58 and '_' not in sequence, sequence=sequence)
        check(name + ' selected five sequence residues survive generation', sequence[:5] == 'MTYKL')
        check(name + ' retained input coordinates are unchanged, not generated structure', torch.allclose(result.coordinates, input_tokens.coordinates, equal_nan=True))
        seen_structure = current_capture['structure_tokens'][0, 1:-1]
        finite_positions = torch.isfinite(current_capture['coordinates'][0, 1:-1, :3]).all(dim=(-1, -2))
        if coordinate_only:
            check(name + ' actual sampling forward masks entire structure-token track', (seen_structure == mask_id).all())
        else:
            check(name + ' actual sampling forward retains absent-coordinate codebook tokens', seen_structure[11:14].tolist() == missing_tokens)
        expected_count = 5 if name.startswith('sparse') else 55
        check(name + ' actual forward receives requested coordinate positions only', int(finite_positions.sum()) == expected_count)
        for key, value in current_capture.items():
            arrays[f'{name}_{key}'] = value.float().numpy() if value.dtype == torch.bfloat16 else value.numpy()
        arrays[f'{name}_output_sequence_tokens'] = result.sequence.numpy()
        result_data = {'case': name, 'sequence': sequence, 'length': len(sequence), 'seconds': time.monotonic() - case_start,
                       'condition_on_coordinates_only': coordinate_only, 'input_structure_tokens_at_insertions': missing_tokens,
                       'actual_forward_structure_tokens_at_insertions': seen_structure[11:14].tolist(),
                       'actual_forward_structure_mask_count': int((seen_structure == mask_id).sum()), 'actual_forward_coordinate_position_count': int(finite_positions.sum()),
                       'output': 'sequence only; carried input coordinates are conditions, not a generated/predicted structure'}
        reports.append(result_data)
        write(output / (name + '.json'), result_data)
        print(name, sequence, round(result_data['seconds'], 3), flush=True)
    pre_hook.remove()
    post_hook.remove()
    for left, right in [('all_coords_default_true', 'all_coords_false'), ('all_coords_default_true', 'sparse_coords_default_true')]:
        maximum = float(np.max(np.abs(arrays[left + '_sequence_logits'] - arrays[right + '_sequence_logits'])))
        check(left + ' vs ' + right + ' changes real model logits', maximum > 0, max_abs_logit_difference=maximum)
    np.savez_compressed(output / 'native-forward-and-output.npz', **arrays)
    write(output / 'generation.json', {'status': 'passed', 'model': 'esm3_sm_open_v1', 'device': 'cpu', 'parameter_dtype': str(next(model.parameters()).dtype),
          'precision': 'pretrained bf16 weights converted exactly to float32 in anonymous mmap; native CPU float32 forward' , 'entrypoint': 'ESM3.generate(ESMProteinTensor, GenerationConfig); native sequence tokenizer decode',
          'seed': 42, 'num_steps': 1, 'temperature': 0.5, 'memory_before': memory_before, 'process_rss_after': psutil.Process().memory_info().rss,
          'seconds_total': time.monotonic() - started, 'cases': reports, 'checks': CHECKS,
          'scope': 'Actual complete sequence generation, no structure/function decoder or folding/fitness evaluation. One sampling step validates transport and masks, not biological quality.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=HERE / 'evidence')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--inspect-only', action='store_true', help='Run small native boundary checks without loading model weights')
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output.resolve()
    output.mkdir(exist_ok=True, parents=True)
    sys.path.insert(0, str(source / 'repositories' / 'esm'))
    sys.path.insert(0, str(source))
    if args.inspect_only:
        request_path = args.request or output / 'html-request.json'
        inspect_boundary(json.loads(request_path.read_text()), output)
        return
    if not args.worker:
        for name in ['generation.json', 'generation-failure.json', 'generation-resource-stop.json', 'all_coords_default_true.json', 'all_coords_false.json', 'sparse_coords_default_true.json', 'native-forward-and-output.npz']:
            (output / name).unlink(missing_ok=True)
        if args.request is None:
            case = output / 'html-actions.json'
            write(case, {'actions': [{'type': 'insert3'}, {'type': 'delete25'}]})
            args.request = output / 'html-request.json'
            bridge = HERE.parents[1] / 'sequence_edit' / 'prototype_file_handoff' / 'export.cjs'
            subprocess.run(['node', str(bridge), str(case), str(args.request)], check=True)
        from protein_workbench_public.worker_process import run_worker
        command = [sys.executable, str(Path(__file__).resolve()), '--source-root', str(source), '--output', str(output), '--worker']
        if args.request:
            command += ['--request', str(args.request.resolve())]
        run_worker(command, cwd=source, log_path=output / 'worker.log', cancelled=lambda: False, label='ESM3 file-input prototype')
        return
    request = json.loads(args.request.read_text())
    proteins = preparation(request, output)
    inspect_boundary(request, output)
    # Abort our worker rather than risking sustained pressure on the user's machine.
    import threading
    import psutil
    def monitor_resources():
        began, low_count = time.monotonic(), 0
        while True:
            available = psutil.virtual_memory().available
            low_count = low_count + 1 if available < 384 * 1024**2 else 0
            if low_count >= 3 or time.monotonic() - began > 600:
                write(output / 'generation-resource-stop.json', {'available_bytes': available, 'elapsed_seconds': time.monotonic() - began, 'reason': 'low available memory' if low_count >= 3 else '600 second time limit'})
                os._exit(75)
            time.sleep(1)
    threading.Thread(target=monitor_resources, daemon=True).start()
    try:
        generation(source, output, *proteins)
    except Exception as error:
        write(output / 'generation-failure.json', {'type': type(error).__name__, 'message': str(error), 'checks_before_failure': CHECKS})
        raise


if __name__ == '__main__':
    main()
