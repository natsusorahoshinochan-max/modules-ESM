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
these identities, so a later real-provider gate must perform that check before its
evidence can satisfy tickets 19 or 20.

| Object | Bytes | ETag |
| --- | ---: | --- |
| `simplefold_100M.ckpt` | 386772550 | `d3f36328118ca08f0aac3a0e910b6829-23` |
| `simplefold_360M.ckpt` | 1454881694 | `7c0603668846e72a0bd8a2c8b43b1151-85` |
| `simplefold_1.6B.ckpt` | 6354525226 | `8547a616a08162144b9591b3e9479b8e-370` |
| `plddt_module_1.6B.ckpt` | 462812900 | `1ed78d3cf12e8558ec45c596b1197ba9-27` |

The SimpleFold ESM2 dependency is recorded as
`facebookresearch/esm@2b369911bb5b4b0dda914521b9475cad1656b2ac`. The upstream
wrapper still names the `torch.hub` `main` alias, so a future retained provider gate
must prove that exact checkout before claiming source-bound evidence.

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
