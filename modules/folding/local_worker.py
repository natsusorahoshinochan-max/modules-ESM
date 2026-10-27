"""Single-use local ESMFold2 worker, launched under model_validation by its Adapter."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from .adapters import _decoded, parameters_for, sdk_msa


def invoke(model, builder, protein_type, input_type, sequence, parameters):
    """Call the official SDK boundary with the exact configured seed and controls."""
    values = parameters_for(parameters, local=True)
    msa = values.pop('msa', None)
    protein = {'id': 'A', 'sequence': sequence}
    if msa is not None:
        protein['msa'] = sdk_msa(msa)
    return builder.fold(model, input_type(sequences=[protein_type(**protein)]), num_diffusion_samples=1, complex_id='prediction', **values)


def main():
    payload = json.loads(Path(sys.argv[1]).read_text())
    settings = payload['settings']
    model_path = Path(settings['model_path']).resolve()
    language_path = Path(settings['language_model_path']).resolve()
    if not (model_path / 'ccd.pkl').is_file():
        raise ValueError('The configured ESMFold2 directory is missing ccd.pkl')
    # Enforce offline model resolution before importing SDK/HF modules.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['ESMCFOLD_CCD_PATH'] = str(model_path / 'ccd.pkl')
    from esm.models.esmfold2 import ESMFold2InputBuilder, ProteinInput, StructurePredictionInput
    from transformers.models.esmfold2.configuration_esmfold2 import ESMFold2Config
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model
    config = ESMFold2Config.from_pretrained(str(model_path), local_files_only=True)
    config.esmc_id = str(language_path)
    model = ESMFold2Model.from_pretrained(str(model_path), config=config, local_files_only=True, esmc_precision='fp32').to(settings['device']).eval()
    builder = ESMFold2InputBuilder(ccd_cache=model_path)
    result = invoke(model, builder, ProteinInput, StructurePredictionInput, payload['sequence'], payload['parameters'])
    decoded = _decoded(result, SimpleNamespace(workdir=Path(payload['workdir'])), local=True)
    (Path(payload['workdir']) / 'esmfold2-result.json').write_text(json.dumps(asdict(decoded), allow_nan=False))


if __name__ == '__main__':
    main()
