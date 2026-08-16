# Provider installation contract

Provider repositories are external, read-only dependencies. They are never copied
into Protein Workbench wheels or sdists and are not repair surfaces for this
project.

## Locked provider sources

| Provider | Source | Commit | Installation |
| --- | --- | --- | --- |
| ESM / Biohub | `https://github.com/Biohub/esm.git` | `917af90b624535eed1e072d343c717e3ec11fef4` | `uv sync --frozen --extra providers` |
| SimpleFold | `https://github.com/apple/ml-simplefold.git` | `c7a5570a6be9f5c695126e27c804e77567209934` | `uv sync --frozen --extra providers` |
| ProteinMPNN | `https://github.com/dauparas/ProteinMPNN.git` | `8907e6671bfbfc92303b5f79c4b5e6ce47cdef57` | external checkout selected with `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` |

The `providers` extra also installs the PyTorch runtime. Model artifacts remain
external downloads and are not release package data. The identifiers below are the
frozen install inputs. Ticket 17 records them but does not claim the real-provider
evidence required by tickets 19 and 20; those gates are valid only when they retain
matching provider identities rather than silently refreshing them.

Before provider import, the gate checks the exact VCS revision and a reviewed
aggregate SHA-256 over every runtime package file. Editable installs additionally
require a clean checkout with no untracked files; normal VCS installs require every
runtime file to carry a SHA-256 `RECORD` entry and to match the same reviewed package
tree digest.

## ESM and Biohub models

The canonical local model is the Hugging Face snapshot
`biohub/esm3-sm-open-v1@47f0545b2b6daf26a93439a3cd610f4f7f3d5478`.
Download that revision explicitly and use `HF_HUB_OFFLINE=1` for reproducible local
runs. Its required weight objects are:

| Object | SHA-256 |
| --- | --- |
| `data/weights/esm3_sm_open_v1.pth` | `5ead5a135c658068db6a4f1b933e72d6110992c4668822e1c0e2dcc53e38acd9` |
| `data/weights/esm3_structure_encoder_v0.pth` | `467acbaee703ba3ccde6e75241a912a316952e5ff071355f85c1d33c68704f40` |
| `data/weights/esm3_structure_decoder_v0.pth` | `3b726258a44274792b40ce7ea307e10c5da09936368a4ffa2970264d909da65b` |
| `data/weights/esm3_function_decoder_v0.pth` | `f76d074efcaccfe21365a4fa96f212dadd66798e1e49d809ab7ffbe025d227c9` |

Remote Biohub weights are service-managed rather than installed artifacts. The
Workbench contract names their versioned service identifiers exactly:
`esm3-medium-2024-08` and `esmfold2-fast-2026-05`.

## SimpleFold models

SimpleFold commit `c7a5570a6be9f5c695126e27c804e77567209934` selects the
following CDN objects. Retain the object ETag and byte count alongside each
download; these are the upstream object identities because the CDN does not expose
versioned URLs or published SHA-256 values. The upstream wrapper does not enforce
these identities, and multipart ETags are not cryptographic content digests. The
Workbench therefore enforces the separately reviewed SHA-256 manifest below:

| Upstream object | Runtime filename | Bytes | ETag | SHA-256 |
| --- | --- | ---: | --- | --- |
| `simplefold_100M.ckpt` | `simplefold_100M.ckpt` | 386772550 | `d3f36328118ca08f0aac3a0e910b6829-23` | `4cd0b8a0b317a6ab8634444fffd78ce84cfd49c20fe927b83c76c36fda5f54bd` |
| `simplefold_360M.ckpt` | `simplefold_360M.ckpt` | 1454881694 | `7c0603668846e72a0bd8a2c8b43b1151-85` | `517338ec36b10ecc774f36b592ffe0fee6a24fa5c7d2fcfa3e3009282d48a49b` |
| `simplefold_1.6B.ckpt` | `simplefold_1.6B.ckpt` | 6354525226 | `8547a616a08162144b9591b3e9479b8e-370` | `aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b` |
| `plddt_module_1.6B.ckpt` | `plddt.ckpt` | 462812900 | `1ed78d3cf12e8558ec45c596b1197ba9-27` | `cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f` |
| `ccd.pkl` | `ccd.pkl` | 345859128 | — | `2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4` |
| `boltz1_conf.ckpt` | `boltz1_conf.ckpt` | 266338304 | — | `219a73ac67535ad0535b9d3fb11fc7dbbcb7a0b71e4b4bb28f0c50cc2ac7f4ee` |

The SimpleFold ESM2 dependency is recorded as
`facebookresearch/esm@2b369911bb5b4b0dda914521b9475cad1656b2ac`. Configure a
clean checkout at that exact commit with
`PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT`. The adapter verifies its Git root, HEAD,
clean status, and the reviewed 32-file runtime source-tree aggregate
`da1fd5e94771906950ccc9b4e789d50b0e8f8c4594608898dbcb14f14e3c50ba`.
It stages and rehashes that exact source subset before import.

The ESM2 loader also deserializes two separate Facebook checkpoint objects. Place
these in `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT`:

| Runtime filename | Bytes | SHA-256 |
| --- | ---: | --- |
| `esm2_t36_3B_UR50D.pt` | 5678116398 | `7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500` |
| `esm2_t36_3B_UR50D-contact-regression.pt` | 6759 | `4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e` |

Both ESM2 objects are copied through no-follow descriptors into the isolated run
root and rehashed. The adapter removes the incompatible Biohub `esm` namespace,
imports Facebook ESM only from the staged source, and calls its local-file loader
with the staged objects using explicit `weights_only=True` deserialization and an
`argparse.Namespace` safe-global allowlist for the upstream metadata. It never
invokes the upstream ESM2 network or `TORCH_HOME` checkpoint loader.

The legacy aggregate SimpleFold acceptance gate covers folding and confidence
evaluation together, so its model root contains all six runtime filenames as
regular non-symlink files. The v2 `folding.fold.simplefold_local` Binding has a
narrower, source-bound closure: `simplefold_100M.ckpt`,
`simplefold_1.6B.ckpt`, `plddt.ckpt`, and `ccd.pkl`, plus the two ESM2 objects
and exact ESM2 source checkout above. It neither uses nor claims
`simplefold_360M.ckpt` or `boltz1_conf.ckpt`; those remain requirements only
for provider operations that actually load them.

Neither adapter invokes the SimpleFold downloader. Each hashes its exact
configured file set, copies it through no-follow file descriptors into the
isolated run root, rehashes the staged copies, and only then imports or invokes
the provider.

The pinned SimpleFold PDB writer pads every record to 80 columns and represents
its final sentinel as an 80-space record without a trailing newline. The folding
Adapter accepts only that exact provider tail, translates it to the canonical
`END` record followed by one newline, and then publishes through the
`protein.structure@4.0.0` Port. Any other provider tail fails at the Adapter
boundary instead of being guessed or repaired.

## mkdssp

The canonical Workflow requires `mkdssp` 4.6.1. The upstream source archive is
`https://github.com/PDB-REDO/dssp/archive/refs/tags/v4.6.1.tar.gz` with SHA-256
`5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3`.
The accepted macOS ARM64 Sequoia Homebrew bottle SHA-256 is
`b9cb866c727431d129fbb11f3c60f0b3c4e325822cb8e3330f86ecb45996595e`.
Provider readiness must report exactly `mkdssp version 4.6.1`; the default binary
path is `/opt/homebrew/bin/mkdssp`.

## ProteinMPNN checkpoints

The locked ProteinMPNN commit contains the supported vanilla model checkpoints.
The adapter verifies the locked Git HEAD, rejects modified tracked provider files,
and enforces the selected checkpoint hash before using it:

| Checkpoint | SHA-256 |
| --- | --- |
| `vanilla_model_weights/v_48_002.pt` | `925f2ca1007bf9b02e0e7f420ff00eb91f50fcc2722f64b42e644ae95adaa131` |
| `vanilla_model_weights/v_48_010.pt` | `db866fae956a28661f926053d630610c55e9fc4bc03922f2aeeb98a37435ccce` |
| `vanilla_model_weights/v_48_020.pt` | `c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd` |
| `vanilla_model_weights/v_48_030.pt` | `c34b7bfb38418ea30989fda3314f4781ac4e3920f9825731cf555f1fed44ac66` |
| `soluble_model_weights/v_48_002.pt` | `0877f840978fe770be6fcec025784d8f50c438571db3260c05e41aa207a7c448` |
| `soluble_model_weights/v_48_010.pt` | `79562f7444f72c84595a1c96010713864865a616f4f3967633493041e169fa6e` |
| `soluble_model_weights/v_48_020.pt` | `7af52d090172c230c7f0e9d21e02203f6b3a38b16db58d3c7a3960e0a9a6e31a` |
| `soluble_model_weights/v_48_030.pt` | `1dd63f1e9fc68a133cc9ef859edf43b489e5ac581cb5624e0b9ec848ff062421` |

Example setup:

```bash
git clone https://github.com/dauparas/ProteinMPNN.git /opt/proteinmpnn
git -C /opt/proteinmpnn checkout 8907e6671bfbfc92303b5f79c4b5e6ce47cdef57
export PROTEIN_WORKBENCH_PROTEINMPNN_ROOT=/opt/proteinmpnn
```

The backend raises a visible `FileNotFoundError` when this root is absent or does
not contain `protein_mpnn_utils.py`; it never falls back to a source-checkout
relative `repositories/` path.
