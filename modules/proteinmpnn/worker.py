"""Isolated native ProteinMPNN process. RNG state belongs exclusively to this call."""
import importlib.util
import json
from pathlib import Path
import random
import secrets
import sys


def run(payload):
    import numpy as np
    import torch
    from .adapters import ALPHABET
    p, settings, entry = payload['parameters'], payload['settings'], payload['entry']
    actual_seed = payload.get('actual_seed')
    if actual_seed is None:
        actual_seed = p['seed'] if p['seed'] else secrets.randbelow(999)
    random.seed(actual_seed)
    np.random.seed(actual_seed)
    torch.manual_seed(actual_seed)
    device = torch.device(settings.get('device', 'cpu'))
    source = Path(settings.get('source', '')) / 'protein_mpnn_utils.py'
    if not source.is_file():
        raise ValueError('Configure existing ProteinMPNN source containing protein_mpnn_utils.py')
    spec = importlib.util.spec_from_file_location('workbench_native_proteinmpnn', source)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    family = 'soluble_model_weights' if p['use_soluble_model'] else 'vanilla_model_weights'
    checkpoint_path = Path(settings.get('weights', '')) / family / (p['model_name'] + '.pt')
    if not checkpoint_path.is_file():
        raise ValueError(f'Configure existing ProteinMPNN weights: {family}/{p["model_name"]}.pt')
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
    model = native.ProteinMPNN(num_letters=21, node_features=128, edge_features=128, hidden_dim=128,
                              num_encoder_layers=3, num_decoder_layers=3, vocab=21,
                              k_neighbors=checkpoint['num_edges'], augment_eps=p['backbone_noise'], dropout=0.1)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.to(device)
    model.eval()
    chains = {key.removeprefix('seq_chain_'): value for key, value in entry.items() if key.startswith('seq_chain_')}
    designed = p['designed_chains']
    chain_dict = {entry['name']: (list(designed), [chain for chain in chains if chain not in designed])}
    def constraint(key, default):
        return {entry['name']: {chain: p[key].get(chain, default) for chain in chains}}
    # Native tied_featurize requires per-chain dictionaries even for unset chains.
    args = (constraint('fixed_positions', []), constraint('omit_AA', []),
            {entry['name']: p['tied_positions']} if p['tied_positions'] else None,
            constraint('pssm', None), {entry['name']: {chain: p['bias_by_res'].get(chain, [[0.0] * 21 for _ in sequence]) for chain, sequence in chains.items()}})
    batch = native.tied_featurize([entry.copy() for _ in range(p['batch_size'])], device, chain_dict, *args)
    (X, S, mask, lengths, chain_M, chain_encoding, orders, visible, masked, masked_lengths,
     chain_M_pos, omit_mask, residue_idx, dihedral, tied, pssm_coef, pssm_bias, pssm_odds,
     bias_by_res, tied_beta) = batch
    if not bool((mask > 0).all()):
        raise ValueError('ProteinMPNN requires complete finite backbone coordinates for every position')
    loss_mask = mask * chain_M * chain_M_pos
    if not bool((loss_mask.sum(dim=1) > 0).all()):
        raise ValueError('ProteinMPNN requires at least one design/scoring position')
    if payload['sequences'] is not None:
        for b, order in enumerate(orders):
            encoded = [ALPHABET.index(aa) for chain in order for aa in payload['sequences'][chain]]
            if len(encoded) != int(lengths[b]):
                raise ValueError('Scoring requires complete sequence correspondence')
            S[b] = torch.tensor(encoded, device=device)
    def split(values, order):
        offset, result = 0, {}
        for chain in order:
            length = len(chains[chain])
            result[chain] = values[offset:offset + length]
            offset += length
        if offset != len(values):
            raise ValueError('Native result length does not match supplied chains')
        return result
    samples = []
    with torch.no_grad():
        for temperature in (p['sampling_temp'] if payload['sequences'] is None else [None]):
            for batch_index in range(p['num_seq_per_target'] // p['batch_size']):
                noise = torch.randn(chain_M.shape, device=device)
                sample = None
                if payload['sequences'] is None:
                    sample_args = dict(mask=mask, temperature=temperature,
                        omit_AAs_np=np.array([aa in p['omit_AAs'] for aa in ALPHABET], dtype=np.float32),
                        bias_AAs_np=np.array([p['bias_AA'].get(aa, 0) for aa in ALPHABET], dtype=np.float32),
                        chain_M_pos=chain_M_pos, omit_AA_mask=omit_mask, pssm_coef=pssm_coef,
                        pssm_bias=pssm_bias, pssm_multi=p['pssm_multi'], pssm_log_odds_flag=p['pssm_log_odds_flag'],
                        pssm_log_odds_mask=(pssm_odds > p['pssm_threshold']).float(), pssm_bias_flag=p['pssm_bias_flag'], bias_by_res=bias_by_res)
                    if p['tied_positions']:
                        sample_args.update(tied_pos=tied[0], tied_beta=tied_beta)
                        sampler = model.tied_sample
                    else:
                        sampler = model.sample
                    sample = sampler(X, noise, S, chain_M, chain_encoding, residue_idx, **sample_args)
                    sampled = sample['S']
                else:
                    sampled = S
                decode = {'use_input_decoding_order': True, 'decoding_order': sample['decoding_order']} if sample is not None else {}
                log_probs = model(X, sampled, mask, chain_M * chain_M_pos, residue_idx, chain_encoding, noise, **decode)
                scores = native._scores(sampled, log_probs, loss_mask)
                global_scores = native._scores(sampled, log_probs, mask)
                residue_nll = -torch.gather(log_probs, 2, sampled.unsqueeze(-1)).squeeze(-1)
                recovery = ((sampled == S).float() * loss_mask).sum(-1) / loss_mask.sum(-1)
                for b in range(p['batch_size']):
                    length = int(lengths[b])
                    symbols = ''.join(ALPHABET[index] for index in sampled[b, :length].tolist())
                    row = {'chains': split(symbols, orders[b]), 'score': float(scores[b]), 'global_score': float(global_scores[b]),
                           'residue_nll': split(residue_nll[b, :length].cpu().tolist(), orders[b]),
                           'design_mask': split(loss_mask[b, :length].cpu().tolist(), orders[b]),
                           'coordinate_mask': split(mask[b, :length].cpu().tolist(), orders[b]),
                           'recovery': float(recovery[b]), 'temperature': temperature, 'batch_index': batch_index,
                           'tool_chain_order': orders[b]}
                    if sample is not None and 'probs' in sample:
                        row['sampling_probabilities'] = split(sample['probs'][b, :length].cpu().tolist(), orders[b])
                    samples.append(row)
    return {'samples': samples, 'actual_seed': actual_seed}


if __name__ == '__main__':
    payload = json.loads(Path(sys.argv[1]).read_text())
    result = run(payload)
    Path(payload['output']).write_text(json.dumps(result, allow_nan=False))
