# ProteinMPNN design and reusable tool call

Install and enable `modules.proteinmpnn:module` for tools and `modules.generation:module` for scientific nodes; add **Design sequences from
backbone**, and bind an explicit structure package. Select the local ProteinMPNN
tool and configure native conditions and sampling in its tool parameter JSON.
The module editor explains limits; its design viewer displays each actual chain, NLL values,
parameters, masks and real residue correspondence. The host's generic ZIP action
exports all declared files. Use the run's Continue action for unfinished batches.
The design node delivers the complete `workbench.proteinmpnn_design` result.
Before folding or another canonical single-chain task, add **Use one design chain
as sequence** and select the actual chain. Empty selection works only for the same
single chain in every sample. The result viewer can add a converter for its
explicitly selected package; full conversion rules are in [generation formats](../generation/FORMAT.md).

Deployment settings are `source` (existing ProteinMPNN directory containing
`protein_mpnn_utils.py`), `weights` (existing root containing
`vanilla_model_weights` and/or `soluble_model_weights`), `python` (existing Python
with PyTorch, NumPy and gemmi), and `device` (`cpu`, `cuda` or `mps`). No assets or
environments are downloaded. The native worker uses the shared supervised machine
lease documented in [local models](../../docs/local-models.md); do not wrap this
Adapter in a second lease. Cancellation terminates the supervised process group.

## Input and native positions

The Adapter independently reads PDB/mmCIF author chain, residue number and
insertion code. It requires a single model, unique chain names, canonical amino
acids, and one unambiguous finite N, CA, C and O per residue. Unsupported components
and ambiguous/missing backbone atoms fail explicitly. Extract the intended protein
or select a conformation/alternate location explicitly before calling this tool.

The native `tied_featurize` input is built directly from those actual residues;
it avoids the PDB parser's synthetic numbering-gap placeholders. Positions follow
coordinate-file residue order within each chain; insertion-coded residues each
occupy their own position. The exact mapping is delivered in `positions`.
Native featurization then sorts designed chains, followed by sorted fixed chains;
`tool_chain_order` records the actual tensor order. Returned sequences and arrays
are split using that order and matched to the original chain positions.

## Parameters

Defaults and parameter behavior follow the pinned upstream
[`protein_mpnn_run.py`](../../repositories/ProteinMPNN/protein_mpnn_run.py) and
[`tied_featurize`, `sample`, `tied_sample`](../../repositories/ProteinMPNN/protein_mpnn_utils.py).
The exposed task uses full-backbone vanilla or soluble models. CA-only prediction,
conditional probability tasks and unconditional probability tasks have distinct
inputs/outputs and are outside this design/scoring call.

| Parameter | Default and actual meaning |
| --- | --- |
| `model_name` | `v_48_020`; also `v_48_002`, `v_48_010`, `v_48_030` |
| `use_soluble_model` | `false`; selects the corresponding existing weight family |
| `backbone_noise` | `0.0` Å; nonnegative augmentation noise standard deviation |
| `seed` | `0` chooses a random actual seed in 0–998, matching the CLI's random-seed range; positive values up to 2³²−1 seed the call directly |
| `num_seq_per_target` | `1`; positive count **per temperature** |
| `batch_size` | `1`; positive native tensor batch size; count must be divisible by it, otherwise the call fails before tool execution |
| `sampling_temp` | `[0.1]`; nonempty list of positive finite sampling temperatures |
| `designed_chains` | `null` means all actual chains; otherwise a nonempty list of unique actual chain names, all other chains are fixed |
| `fixed_positions` | `{}`; chain → native 1-based position list |
| `tied_positions` | `[]`; list of groups, each `{chain: [[positions], [finite weights]]}` with at least two positions in a group |
| `omit_AAs` | `"X"`; globally omitted alphabet symbols |
| `bias_AA` | `{}`; alphabet symbol → finite additive bias |
| `bias_by_res` | `{}`; chain → one 21-column bias row per chain position |
| `omit_AA` | `{}`; chain → list of `[[positions], [alphabet symbols]]` pairs |
| `pssm` | `{}`; chain → native `pssm_coef`, `pssm_bias`, `pssm_log_odds` arrays; lengths match the entire chain and matrix rows have 21 alphabet columns |
| `pssm_multi` | `0.0`; finite 0–1 mixing weight |
| `pssm_threshold` | `0.0`; finite log-odds threshold |
| `pssm_log_odds_flag`, `pssm_bias_flag` | `false`; actual native boolean switches |

All 21-column matrices use `ACDEFGHIKLMNPQRSTVWYX`. Unset per-chain controls use
native defaults. Unknown controls, incomplete matrices, invalid chain/position
references, and count/batch mismatches fail explicitly. The checkpoint selected by
the family and model name supplies `num_edges`; its weights are loaded data-only.
Python, NumPy and PyTorch are all seeded in the isolated worker. The parent task's
RNG state is unaffected. The design node fixes each backbone's random seed
proposal for continuation; a positive user seed always takes precedence.

## Public reusable call

`workbench.proteinmpnn.call` is owned by this module. Implementations have
`call(request, parameters, runtime) -> MPNNResult`; types live in
`modules.proteinmpnn.contract`. Authors reusing this Python API declare an explicit
installation dependency on the `protein-workbench` distribution containing
`modules.proteinmpnn`; consumers of result files need no producer installation.

`MPNNRequest` contains a completed workdir-relative `structure_path`, its
`structure_format` (`pdb` or `mmcif`), optional `sequences`, and optional
`random_seed`, `complete_target` and `conditions`. A complete edited mmCIF target uses the full polymer position table, rejects missing N/CA/C/O at any target position, and applies explicit fixed residue conditions. Its coordinate selection must contain every N/CA/C/O position. The complete single-chain target retains its source author chain separately from label chain numbering; ambiguous mixed author chains fail. No unresolved target position is skipped. `sequences=None` designs. A chain → sequence map scores existing
sequences; it must exactly cover every chain and every residue before any tool
call. Missing chains, prefixes, extra residues and ambiguous positions fail;
existing sequence tails are never used to complete the request. `random_seed` is
the caller's fixed proposal for `seed=0`, including actual zero. Without a proposal
the Adapter chooses a fresh actual seed. Positive user seeds are passed directly.

`MPNNResult` contains the complete actual `positions`, one `samples` item per
requested sequence per temperature (score mode has no temperature loop),
`actual_seed`, and effective `parameters`. Sample content and score meanings are
specified in [generation formats](../generation/FORMAT.md). In score mode `chains` contains the unchanged
supplied sequence mapping; `temperature` is null, probabilities are absent, and
forward uses `chain_M * chain_M_pos` exactly as the native CLI. `num_seq_per_target`
controls repeated stochastic decoding evaluations, with exact batch divisibility.
Exceptions fail the request. No retry or task change is added by this local tool.
The caller owns batch organization and continuation. Tools honor runtime
cancellation and return only completed values/files; the caller encodes Delivery.

## Representative verification

Create a JSON configuration containing `structure` (existing coordinate path),
`format`, actual `model` number (default 1), `settings`, and optional `parameters`.
Run through the application, import, Adapter, persistence and result reader:

```bash
.venv/bin/python -m modules.proteinmpnn.verify configuration.json --output /absolute/new-verification-data
```

This prints per-chain lengths, actual seeds, position counts and natural
scores read back from persisted package files. Choose a new output directory for
a distinct verification. Original research files remain unchanged.
