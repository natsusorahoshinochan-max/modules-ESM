"""Native esm HF and fixed Biohub SDK representation boundaries."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from protein_workbench_public.module_api import Tool

REMOTE_MODELS = ('esmc-300m-2024-12', 'esmc-600m-2024-12', 'esmc-6b-2024-12')
LOCAL_MEAN = 'mean of actual residue positions; excludes added special tokens and padding'
REMOTE_MEAN = 'Biohub service mean embedding; service pooling token exclusions are unspecified'


def tokenizer():
    from esm.models.esmc.tokenizer import EsmcTokenizer
    return EsmcTokenizer()


def token_positions(sequence, ids, vocabulary):
    names = {value: key for key, value in vocabulary.get_vocab().items()}
    tokens, indices = [], []
    for index, token_id in enumerate(ids):
        item = {'index': index, 'id': token_id}
        if token_id in names:
            item['name'] = names[token_id]
        if token_id not in vocabulary.all_special_ids:
            residue_index = len(indices)
            if residue_index >= len(sequence) or names.get(token_id) != sequence[residue_index]:
                raise ValueError('ESMC encoded token does not correspond to the supplied residue')
            item['sequence_index'] = residue_index + 1
            indices.append(index)
        tokens.append(item)
    if len(indices) != len(sequence):
        raise ValueError('ESMC encoded tokens do not cover the supplied sequence')
    return tokens, indices, names


def array(value):
    if hasattr(value, 'detach'):
        value = value.detach().cpu().float().numpy()
    output = np.asarray(value)
    if output.dtype.kind != 'f' or not np.isfinite(output).all():
        raise ValueError('ESMC must return finite floating point values')
    return output


def normalize(sequence, ids, result, vocabulary, *, embedding, logits, local):
    tokens, indices, names = token_positions(sequence, ids, vocabulary)
    mean, matrix = None, None
    if embedding:
        if local:
            hidden = array(result.last_hidden_state)
            if hidden.ndim != 3 or hidden.shape[:2] != (1, len(ids)):
                raise ValueError('ESMC hidden states do not cover encoded token positions')
            mean = hidden[0, indices].mean(axis=0)
        else:
            if result.mean_embedding is None:
                raise ValueError('Biohub omitted the requested mean embedding')
            mean = array(result.mean_embedding)
            while mean.ndim > 1 and mean.shape[0] == 1:
                mean = mean[0]
            if mean.ndim != 1 or not mean.size:
                raise ValueError('Biohub mean embedding must have a single embedding axis')
    if logits:
        value = result.logits if local else result.logits.sequence
        if value is None:
            raise ValueError('ESMC omitted the requested logits')
        matrix = array(value)
        if matrix.ndim == 3 and matrix.shape[0] == 1:
            matrix = matrix[0]
        if matrix.ndim != 2 or matrix.shape[0] != len(ids) or matrix.shape[1] < 1:
            raise ValueError('ESMC logits do not cover encoded token positions')
    return SimpleNamespace(tokens=tokens, mean=mean, logits=matrix,
                           columns=[] if matrix is None else [{'index': index, **({'name': names[index]} if index in names else {})} for index in range(matrix.shape[1])],
                           mean_semantics=LOCAL_MEAN if local else REMOTE_MEAN)


def load_local(settings):
    """Only this heavy checkpoint loading seam is replaced in local contract tests."""
    from esm.models.esmc.model import EsmcForMaskedLM
    model_path = Path(settings.get('model_path', ''))
    if not settings.get('model_path') or not model_path.is_dir():
        raise ValueError('Configure an existing ESMC Hugging Face model directory')
    device = settings.get('device', 'cpu')
    if device not in ('cpu', 'mps', 'cuda'):
        raise ValueError('ESMC device must be cpu, mps or cuda')
    return EsmcForMaskedLM.from_pretrained(str(model_path), device=device, local_files_only=True).eval()


def create_local(settings):
    def represent(sequence, parameters, runtime):
        import torch
        if parameters:
            raise ValueError('Local ESMC has no tool computation parameters')
        vocab = tokenizer()
        encoded = vocab(sequence, return_tensors='pt')
        ids = encoded['input_ids'][0].tolist()
        model = load_local(settings)
        try:
            with torch.inference_mode():
                result = model(**{key: value.to(settings.get('device', 'cpu')) for key, value in encoded.items()})
            normalized = normalize(sequence, ids, result, vocab, embedding=runtime.embedding, logits=runtime.logits, local=True)
            normalized.model = {'backend': 'local', 'configuration': model.config.to_dict()}
            normalized.parameters = {}
            return normalized
        finally:
            del model
    return represent


def remote_client(settings, model):
    from esm.sdk.forge import ESMCForgeInferenceClient
    if not settings.get('token'):
        raise ValueError('Configure the Biohub credential in ESMC module settings')
    return ESMCForgeInferenceClient(model=model, token=settings['token'], url=settings.get('service_url') or 'https://biohub.ai')


def create_remote(settings, *, client_factory=remote_client):
    def represent(sequence, parameters, runtime):
        from esm.sdk.api import ESMProtein, ESMProteinError, LogitsConfig
        if set(parameters) - {'model'}:
            raise ValueError('Unknown Biohub ESMC parameters')
        model = parameters.get('model', 'esmc-6b-2024-12')
        if model not in REMOTE_MODELS:
            raise ValueError('Select an actual Biohub ESMC model ID')
        client = client_factory(settings, model)
        try:
            encoded = client.encode(ESMProtein(sequence=sequence))
            if isinstance(encoded, ESMProteinError):
                raise RuntimeError(f'Biohub ESMC encode failed: {encoded.error_code}')
            result = client.logits(encoded, LogitsConfig(sequence=runtime.logits, return_mean_embedding=runtime.embedding))
            if isinstance(result, ESMProteinError):
                raise RuntimeError(f'Biohub ESMC logits failed: {result.error_code}')
            normalized = normalize(sequence, encoded.sequence.detach().cpu().reshape(-1).tolist(), result, tokenizer(), embedding=runtime.embedding, logits=runtime.logits, local=False)
            normalized.model = {'backend': 'biohub', 'id': model}
            normalized.parameters = {'model': model}
            return normalized
        finally:
            client.close()
    return represent


def tools():
    return (Tool('workbench.esmc.local', {'zh-CN': 'ESMC · 本地', 'en': 'ESMC · Local'}, 'workbench.esmc.representation', create_local),
            Tool('workbench.esmc.biohub', 'ESMC · Biohub', 'workbench.esmc.representation', create_remote,
                 parameters={'model': {'title': {'zh-CN': '模型', 'en': 'Model'}, 'type': 'string', 'enum': list(REMOTE_MODELS), 'default': 'esmc-6b-2024-12'}}))
