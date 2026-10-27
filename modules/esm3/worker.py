"""One isolated local native generation; supervisor owns the model lease."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from .adapters import protein_for, save_result
from modules.generation.contract import GenerateRequest


def load_model(settings):
    from .local_runtime import load_local_esm3_client
    model_path = Path(settings.get('model_path', ''))
    if not settings.get('model_path') or not model_path.is_dir():
        raise ValueError('Configure an existing local ESM3 snapshot directory')
    files = ('data/weights/esm3_sm_open_v1.pth', 'data/weights/esm3_structure_encoder_v0.pth',
             'data/weights/esm3_structure_decoder_v0.pth', 'data/weights/esm3_function_decoder_v0.pth',
             'data/hyperplanes_8bit_58641.npz', 'data/uniref90_and_mgnify90_residue_annotations_gt_1k_proteins.csv')
    if any(not (model_path / file).is_file() for file in files):
        raise ValueError('Local ESM3 snapshot is missing required assets; no model is downloaded')
    return load_local_esm3_client(SimpleNamespace(model_path=str(model_path), device=settings.get('device') or 'cpu'), model_name='esm3_sm_open_v1')


def run(payload, *, model_loader=load_model):
    import torch
    from esm.sdk.api import GenerationConfig
    settings = payload['settings']
    device = settings.get('device') or 'cpu'
    if device not in ('cpu', 'mps', 'cuda'):
        raise ValueError('ESM3 device must be cpu, cuda or mps')
    parameters = payload['parameters']
    seed = parameters['seed']
    protein = protein_for(GenerateRequest(payload['track'], payload['tracks']), local=True)
    protein.potential_sequence_of_concern = parameters['potential_sequence_of_concern']
    config = GenerationConfig(track=payload['track'], **{name: value for name, value in parameters.items() if name not in ('seed', 'potential_sequence_of_concern')})
    model = model_loader(settings)
    # The worker process owns its RNG; checkpoint construction precedes sampling.
    torch.manual_seed(seed)
    if device == 'mps':
        torch.mps.manual_seed(seed)
    try:
        with torch.inference_mode():
            result = model.generate(protein, config)
        runtime = SimpleNamespace(workdir=Path(payload['output']).parent)
        output = save_result(result, config, parameters, runtime, seed=seed)
        Path(payload['output']).write_text(json.dumps(asdict(output), allow_nan=False))
    finally:
        del model


if __name__ == '__main__':
    run(json.loads(Path(sys.argv[1]).read_text()))
