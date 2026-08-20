# Provider installation contract

Status: current operational contract for the active Catalog generation.

Provider repositories are external, read-only dependencies. They are never copied
into Protein Workbench wheels or sdists and are not repair surfaces for this
project.

This document owns source installation, local asset preparation, and environment
selection. Active Module Package Method and Execution Binding descriptors own the
scientific model, operation, fixed configuration, and exact result-affecting asset
identity. Environment Configuration supplies locations for those already selected
facts; it does not select a different scientific route.

## Locked provider sources

| Provider | Source | Commit | Installation |
| --- | --- | --- | --- |
| ESM / Biohub | `https://github.com/Biohub/esm.git` | `917af90b624535eed1e072d343c717e3ec11fef4` | `uv sync --frozen --extra providers` |
| SimpleFold | `https://github.com/apple/ml-simplefold.git` | `c7a5570a6be9f5c695126e27c804e77567209934` | `uv sync --frozen --extra providers` |
| ProteinMPNN | `https://github.com/dauparas/ProteinMPNN.git` | `8907e6671bfbfc92303b5f79c4b5e6ce47cdef57` | external checkout selected with `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` |

The `providers` extra also installs the PyTorch runtime. Model artifacts remain
external downloads and are not release package data. The identifiers below are
the frozen inputs used by the single current Acceptance Campaign.

Before Provider entry, the owner checks the installed package's PEP 610 or
editable-checkout Git revision. It does not hash an entire package tree, require
a clean working tree, or revalidate every `RECORD` entry. Result-affecting models,
checkpoints, and required assets are admitted separately below.

## Current remote Provider service identities

Remote Provider weights are service-managed rather than installed artifacts. The
active Catalog names these service identities exactly:

| Route | Current model | Contract owner |
| --- | --- | --- |
| Biohub ESMC | `esmc-600m-2024-12` | `esm3` Method/Binding |
| Biohub ESM-3 medium | `esm3-medium-2024-08` | `esm3` Method/Binding |
| Biohub ESM-3 open | `esm3-open-2024-03` | `esm3` Method/Binding |
| Biohub ESMFold2 | `esmfold2-fast-2026-05` | `folding` Method/Binding |

Credentials and endpoint configuration make an exact Binding ready; they cannot
replace these model identities or add another route. The installed Biohub gates in
[`backend-verification.md`](backend-verification.md) prove all four current service
identities through public Runs.

## Current local ESM-3 assets

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

## Current local ESMFold2 assets

The local folding Binding fixes two Hugging Face snapshots:

| Role | Model | Revision | Environment Configuration |
| --- | --- | --- | --- |
| Folding model | `biohub/ESMFold2` | `1ebf0e3481a5184eb6171d40615c79e384b48796` | `PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT` |
| Language model | `biohub/ESMC-6B` | `45b0fa5d7fb06faefbd5e3b89bdcef35d564e79a` | `PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT` |

The current required filenames and SHA-256 manifests are owned once by
[`modules/folding/esmfold2_contract.py`](../modules/folding/esmfold2_contract.py).
Readiness admits those exact manifests before Provider entry; the local operation
then trusts the admitted assets. The environment cannot select another checkpoint,
precision, device, or model identity.

## Current SimpleFold assets

SimpleFold commit `c7a5570a6be9f5c695126e27c804e77567209934` selects the
following CDN objects. Retain the object ETag and byte count alongside each
download; these are the upstream object identities because the CDN does not expose
versioned URLs or published SHA-256 values. The upstream wrapper does not enforce
these identities, and multipart ETags are not cryptographic content digests. The
Workbench therefore enforces the separately reviewed SHA-256 manifest below:

| Upstream object | Runtime filename | Bytes | ETag | SHA-256 |
| --- | --- | ---: | --- | --- |
| `simplefold_100M.ckpt` | `simplefold_100M.ckpt` | 386772550 | `d3f36328118ca08f0aac3a0e910b6829-23` | `4cd0b8a0b317a6ab8634444fffd78ce84cfd49c20fe927b83c76c36fda5f54bd` |
| `simplefold_1.6B.ckpt` | `simplefold_1.6B.ckpt` | 6354525226 | `8547a616a08162144b9591b3e9479b8e-370` | `aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b` |
| `plddt_module_1.6B.ckpt` | `plddt.ckpt` | 462812900 | `1ed78d3cf12e8558ec45c596b1197ba9-27` | `cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f` |
| `ccd.pkl` | `ccd.pkl` | 345859128 | — | `2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4` |

The SimpleFold ESM2 dependency is recorded as
`facebookresearch/esm@2b369911bb5b4b0dda914521b9475cad1656b2ac`. Configure a
checkout at that exact commit with
`PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT`. The adapter verifies its Git root, HEAD,
and the reviewed result-affecting runtime source-tree aggregate
`da1fd5e94771906950ccc9b4e789d50b0e8f8c4594608898dbcb14f14e3c50ba`.
It then stages that already admitted source subset for namespace isolation.

The ESM2 loader also deserializes two separate Facebook checkpoint objects. Place
these in `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT`:

| Runtime filename | Bytes | SHA-256 |
| --- | ---: | --- |
| `esm2_t36_3B_UR50D.pt` | 5678116398 | `7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500` |
| `esm2_t36_3B_UR50D-contact-regression.pt` | 6759 | `4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e` |

Both ESM2 objects are hashed once at Readiness and copied into the isolated run
root. The adapter removes the incompatible Biohub `esm` namespace,
imports Facebook ESM only from the staged source, and calls its local-file loader
with the staged objects using explicit `weights_only=True` deserialization and an
`argparse.Namespace` safe-global allowlist for the upstream metadata. It never
invokes the upstream ESM2 network or `TORCH_HOME` checkpoint loader.

The folding and confidence gates use separate result-affecting asset closures.
The `folding.fold.simplefold_local` Binding uses `simplefold_100M.ckpt`,
`simplefold_1.6B.ckpt`, `plddt.ckpt`, and `ccd.pkl`, plus the two ESM2 objects
and exact ESM2 source checkout above. No other upstream SimpleFold checkpoint is a
current product capability.

Neither adapter invokes the SimpleFold downloader. Each hashes its exact
configured file set once at the Adapter-owned Readiness boundary, stages it,
then trusts the staged files during Provider invocation.

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
Provider Readiness must report exactly `mkdssp version 4.6.1`; the binary must be
selected by the absolute `PROTEIN_WORKBENCH_MKDSSP_BINARY` path.
`/opt/homebrew/bin/mkdssp` is one accepted macOS ARM64 example, not a default or
fallback.

## Current ProteinMPNN checkpoint

The current design and score Methods both fix
`vanilla_model_weights/v_48_020.pt`. The Adapter verifies the locked Git HEAD and
this checkpoint hash once before using it:

| Checkpoint | SHA-256 |
| --- | --- |
| `vanilla_model_weights/v_48_020.pt` | `c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd` |

Example setup:

```bash
git clone https://github.com/dauparas/ProteinMPNN.git /opt/proteinmpnn
git -C /opt/proteinmpnn checkout 8907e6671bfbfc92303b5f79c4b5e6ce47cdef57
export PROTEIN_WORKBENCH_PROTEINMPNN_ROOT=/opt/proteinmpnn
```

The backend raises a visible `FileNotFoundError` when this root is absent or does
not contain `protein_mpnn_utils.py`; it never falls back to a source-checkout
relative `repositories/` path.

Other checkpoints present in the upstream repository are not current Workbench
capabilities and do not belong in this contract.

## Current solubility Provider assets

The `solubility` Module Package owns two exact local Provider asset closures:

| Binding family | Environment Configuration | Current identity owner |
| --- | --- | --- |
| project-maintained SoluProt full/no-TM Methods | `PROTEIN_WORKBENCH_SOLUPROT_ROOT` | `modules/solubility` Method/Binding descriptors |
| source-bound Protein-Sol Method | `PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT` | `modules/solubility` Method/Binding descriptors |

The exact source, runtime, model, database, tool, and digest manifests are declared
once in [`modules/solubility`](../modules/solubility/package.py). The configured
root must contain that already selected closure; it cannot select another model or
turn an upstream inventory into a new product capability.

## Environment Configuration rules

Environment Configuration supplies only locations, credentials, and other
deployment facts required by an exact active Binding:

- required Provider filesystem paths are explicit and absolute;
- a missing or mismatched source, model, checkpoint, binary, or credential fails
  the Binding's Readiness before Provider entry;
- no owner searches `repositories/`, another workspace, an undeclared downloader
  cache, or a network location as a fallback; an explicitly selected
  `HF_HUB_CACHE`/`HF_HOME` remains normal Environment Configuration;
- environment values cannot change model identity, Method semantics, scientific
  parameters, device/precision fixed by the Method, or the selected route;
- after the owner admits an exact source/asset closure once, internal Provider
  execution trusts it and does not repeat the same proof.

The exact variable set for each installed gate is maintained in
[`backend-verification.md`](backend-verification.md#trusted-provider-environment-configuration).
