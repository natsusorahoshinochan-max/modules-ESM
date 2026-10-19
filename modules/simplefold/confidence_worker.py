"""Pinned SimpleFold geometry → features → latent → head, without a sampler.

Run in the isolated worker. Public helpers expose the actual Adapter composition
for contract checks that isolate only expensive neural model calls.
"""
import gc
import json
from pathlib import Path
import pickle
import sys


def prepare_geometry(payload):
    import gemmi
    import torch
    from boltz_data_pipeline import const
    from boltz_data_pipeline.types import Input
    from boltz_data_pipeline.tokenize.boltz_protein import BoltzTokenizer
    from boltz_data_pipeline.feature.featurizer import BoltzFeaturizer
    from utils.mmcif_utils import parse_mmcif, convert_atom_name
    from utils.datamodule_utils import collate, extract_sequence_from_tokens
    from modules.structure_confidence import positions_for

    content = Path(payload['structure_path']).read_bytes()
    positions = positions_for(content, payload['structure_format'])
    if positions != payload['positions']:
        raise ValueError('Original structure residue mapping differs from the confidence request')
    from modules.simplefold.confidence import validate_geometry
    structure = validate_geometry(content, payload['structure_format'])
    originals = []
    for chain_index, chain in enumerate(structure[0]):
        chain.name = f'C{chain_index}'
        for index, residue in enumerate(chain):
            expected = const.ref_atoms[residue.name]
            actual = {atom.name: atom for atom in residue}
            if set(actual) != set(expected):
                position = positions[len(originals)]
                raise ValueError(f'SimpleFold cannot completely project atoms at {position}: missing {sorted(set(expected) - set(actual))}, unsupported {sorted(set(actual) - set(expected))}')
            originals.append((residue.name, actual))
            residue.seqid = gemmi.SeqId(index + 1, ' ')
            residue.subchain = f'C{chain_index}'
    structure.setup_entities()
    temporary = Path(payload['workdir']) / 'simplefold-tool-input.cif'
    structure.make_mmcif_document().write_file(str(temporary))
    with Path(payload['settings']['ccd_path']).open('rb') as reader:
        components = pickle.load(reader)
    tool_structure = parse_mmcif(str(temporary), components, use_assembly=False).data
    if len(tool_structure.residues) != len(originals) or not tool_structure.mask.all():
        raise ValueError('SimpleFold parser did not retain every original residue and chain')
    for residue, (name, original_atoms) in zip(tool_structure.residues, originals, strict=True):
        if residue['name'] != name or not residue['is_standard']:
            raise ValueError('SimpleFold parser changed residue correspondence')
        atom_slice = tool_structure.atoms[residue['atom_idx']:residue['atom_idx'] + residue['atom_num']]
        names = {convert_atom_name(atom): atom for atom in original_atoms}
        if len(atom_slice) != len(names) or any(tuple(atom['name']) not in names for atom in atom_slice):
            raise ValueError('SimpleFold parser changed original atom correspondence')
        for atom in atom_slice:
            original = original_atoms[names[tuple(atom['name'])]]
            if atom['element'] != original.element.atomic_number:
                raise ValueError('SimpleFold atom element differs from original structure')
            # Explicit atom-name projection restores original coordinates even when
            # upstream renames/reorders symmetric atoms (e.g. arginine NH1/NH2).
            atom['coords'] = [original.pos.x, original.pos.y, original.pos.z]
            atom['is_present'] = True
    # Upstream parse_mmcif assigns every protein entity=0. Give separate chains
    # separate entities so ESM sequence extraction retains every chain boundary.
    for index, chain in enumerate(tool_structure.chains):
        chain['entity_id'] = index
        chain['sym_id'] = 0
    tokenized = BoltzTokenizer().tokenize(Input(tool_structure, {}))
    if len(tokenized.tokens) != len(positions) or sum(int(t['atom_num']) for t in tokenized.tokens) != len(tool_structure.atoms):
        raise ValueError('SimpleFold tokenizer did not cover every original residue and atom')
    features = BoltzFeaturizer().process(tokenized)
    features['aa_seq'] = extract_sequence_from_tokens(tokenized)
    features['num_repeats'] = torch.tensor(1)
    features['max_num_tokens'] = torch.tensor(len(positions), dtype=torch.long)
    features['cropped_num_tokens'] = torch.tensor(len(positions), dtype=torch.long)
    return collate([features]), positions


def evaluate_geometry(batch, latent_model, head):
    import torch
    t = torch.ones(batch['coords'].shape[0], device=batch['coords'].device)
    latent = latent_model(batch['coords'], t, batch)['latent']
    output = head(latent.detach(), batch)['plddt']
    return output[0].detach().cpu().tolist()


def run(payload):
    import torch
    import simplefold
    provider = Path(simplefold.__file__).resolve().parent
    sys.path.insert(0, str(provider))
    sys.path.insert(0, payload['settings']['esm2_source'])
    from esm.pretrained import load_model_and_alphabet_core
    from utils.esm_utils import _af2_to_esm
    from processor.protein_processor import ProteinDataProcessor
    from simplefold import inference as sdk
    import hydra
    from omegaconf import OmegaConf

    batch, positions = prepare_geometry(payload)
    settings = payload['settings']
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    checkpoint = Path(settings['esm2_checkpoint'])
    print('SimpleFold confidence: existing geometry accepted; preparing ESM2 features', flush=True)
    state = torch.load(checkpoint, map_location='cpu', weights_only=False, mmap=True)
    regression = torch.load(checkpoint.with_name(checkpoint.stem + '-contact-regression.pt'), map_location='cpu', weights_only=False)
    esm_model, alphabet = load_model_and_alphabet_core(checkpoint.stem, state, regression)
    del state, regression
    esm_model = esm_model.eval().to(device)
    processor = ProteinDataProcessor(device=device, scale=16.0, ref_scale=5.0, multiplicity=1, inference_multiplicity=1, backend='torch')
    with torch.inference_mode():
        batch = processor.preprocess_inference(batch, esm_model=esm_model, esm_dict=alphabet, af2_to_esm=_af2_to_esm(alphabet).to(device))
    del esm_model, alphabet
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    def load(name, checkpoint_name):
        config = OmegaConf.load(sdk.get_config_path(f'configs/model/architecture/{name}.yaml'))
        state = torch.load(Path(settings['model_path']) / checkpoint_name, map_location='cpu', weights_only=False, mmap=True)
        model = hydra.utils.instantiate(config)
        model.load_state_dict(state, strict=True, assign=True)
        return model.eval().to(device)

    print('SimpleFold confidence: evaluating original geometry with latent/head', flush=True)
    latent = load('foldingdit_1.6B', 'simplefold_1.6B.ckpt')
    head = load('plddt_module', 'plddt.ckpt')
    with torch.inference_mode():
        values = evaluate_geometry(batch, latent, head)
    if len(values) != len(positions):
        raise ValueError('SimpleFold head did not return every requested residue')
    (Path(payload['workdir']) / 'simplefold-confidence.json').write_text(json.dumps({'positions': positions, 'plddt': values, 'context': {'backend': 'torch', 'device': str(device), 'latent_dtype': str(next(latent.parameters()).dtype)}}, allow_nan=False))
    print('SimpleFold confidence: original geometry scores completed', flush=True)


if __name__ == '__main__':
    run(json.loads(Path(sys.argv[1]).read_text()))
