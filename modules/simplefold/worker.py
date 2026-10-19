"""Isolated pinned upstream SDK invocation using existing local resources only."""
import gc
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from copy import deepcopy


def run(payload):
    import torch
    import simplefold
    # Upstream imports its own model/utils packages by these top-level names.
    provider = Path(simplefold.__file__).resolve().parent
    sys.path.insert(0, str(provider))
    # Keep Facebook ESM separate from the Biohub esm namespace in the host.
    sys.path.insert(0, payload['settings']['esm2_source'])
    from esm.pretrained import load_model_and_alphabet_core
    from simplefold import inference as sdk
    from utils.esm_utils import _af2_to_esm
    import hydra
    from omegaconf import OmegaConf
    from model.torch.sampler import EMSampler

    settings = payload['settings']
    args = SimpleNamespace(**payload['parameters'], backend='torch', nsample_per_protein=1, ckpt_dir=settings['model_path'])
    work = Path(payload['workdir'])
    artifacts = work / 'simplefold-native'
    artifacts.mkdir()
    torch.manual_seed(args.seed)
    import random
    import numpy as np
    random.seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    tokenizer, featurizer, processor, flow, sampler = sdk.initialize_others(args, device)
    sampler = EMSampler(num_timesteps=args.num_steps, t_start=1e-4, tau=args.tau, log_timesteps=args.log_timesteps, w_cutoff=.99)
    fasta = artifacts / 'input.fasta'
    fasta.write_text(f">input\n{payload['sequence']}\n")
    sdk.process_fastas(data=[fasta], out_dir=artifacts, ccd_path=Path(settings['ccd_path']))
    checkpoint = Path(settings['esm2_checkpoint'])
    print('SimpleFold: preparing local ESM2 features', flush=True)
    data = torch.load(checkpoint, map_location='cpu', weights_only=False, mmap=True)
    regression = torch.load(checkpoint.with_name(checkpoint.stem + '-contact-regression.pt'), map_location='cpu', weights_only=False)
    esm_model, alphabet = load_model_and_alphabet_core(checkpoint.stem, data, regression)
    del data, regression
    esm_model = esm_model.eval().to(device)
    structures = list(artifacts.glob('structures/*.npz'))
    if len(structures) != 1:
        raise ValueError('SimpleFold FASTA preparation did not produce exactly one structure')
    with torch.inference_mode():
        batch, structure, record = sdk.process_one_inference_structure(structures[0], artifacts / 'records' / f'{structures[0].stem}.json', tokenizer, featurizer, processor, esm_model, alphabet, _af2_to_esm(alphabet).to(device))
    del esm_model, alphabet
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    def load_model(name, checkpoint_name):
        config = OmegaConf.load(sdk.get_config_path(f'configs/model/architecture/{name}.yaml'))
        state = torch.load(Path(settings['model_path']) / checkpoint_name, map_location='cpu', weights_only=False, mmap=True)
        model = hydra.utils.instantiate(config)
        model.load_state_dict(state, strict=True, assign=True)
        return model.eval().to(device)

    print('SimpleFold: sampling structure', flush=True)
    model = load_model('foldingdit_' + args.simplefold_model.removeprefix('simplefold_'), args.simplefold_model + '.ckpt')
    latent = head = None
    if args.plddt:
        latent = load_model('foldingdit_1.6B', 'simplefold_1.6B.ckpt')
        head = load_model('plddt_module', 'plddt.ckpt')
    with torch.inference_mode():
        coordinates, mask, plddts = sdk.generate_structure(args, batch, sampler, flow, processor, model, latent, head, device)
        output = sdk.process_structure(deepcopy(structure), coordinates[0], mask[0], record, backend='torch')
        sdk.save_structure(output, work, 'simplefold', output_format=args.output_format, plddts=plddts[0] if plddts is not None else None)
    if args.plddt and plddts is None:
        raise ValueError('SimpleFold omitted requested native pLDDT')
    result = {'structure_path': 'simplefold.pdb' if args.output_format == 'pdb' else 'simplefold.cif', 'structure_format': args.output_format}
    if plddts is not None:
        result['plddt'] = (plddts[0].detach().cpu() / 100).tolist()
    (work / 'simplefold-result.json').write_text(json.dumps(result, allow_nan=False))
    print('SimpleFold: native output completed', flush=True)


if __name__ == '__main__':
    run(json.loads(Path(sys.argv[1]).read_text()))
