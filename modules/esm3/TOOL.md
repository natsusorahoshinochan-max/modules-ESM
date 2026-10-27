# ESM3 adapters

Install `modules.esm3:module` for tool implementations and deployment settings. Scientific nodes and their output formats are provided separately by [generation](../generation/FORMAT.md). ESM3 implements the operation-owned [multitrack contract](../generation/TOOL.md).

The Adapter accepts the operation's prepared values and gaps. It translates sequence and secondary-structure nulls to native `_`, missing coordinates to NaN, and named atoms to atom37. Unsupported atom names and invalid aligned tracks fail before inference. Atom37 layout and token offsets remain internal to this Adapter.

`tracks.sequence` is a list of values from `ACDEFGHIKLMNPQRSTVWYXBZUO.-|` or null; `|` is the actual native chain separator. Secondary structure is an aligned list of DSSP8 values `GHITEBSC` or null. SASA accepts finite numbers/null; direct local tool calls also accept the pinned tokenizer vocabulary. Coordinates are aligned dictionaries of actual atom names and finite XYZ values, or null. Annotations are `{label,start,end}` with one-based inclusive bounds; labels must be recognized by the selected ESM3 service or local vocabulary. `potential_sequence_of_concern` is an explicit boolean tool parameter (default false), passed to ESMProtein separately from GenerationConfig. Unsupported inputs fail without dropping fields. Studio selection and permission state are absent from this boundary.

Each call preserves every returned native track and natural metric in its closed `values_file`. Coordinates are native atom37 in Å, with missing values encoded as null; their second axis is `N CA C CB O CG CG1 CG2 OG OG1 SG CD CD1 CD2 ND1 ND2 OD1 OD2 SD CE CE1 CE2 CE3 NE NE1 NE2 OE1 OE2 CH2 NH1 NH2 OH CZ CZ2 CZ3 NZ OXT`. The Adapter also returns portable tracks with named coordinates for editor round-trips; consumers use these instead of decoding this private atom axis.

Natural metrics keep actual values and axes: pLDDT is 0–1, pTM retains scalar or size-1 batch shape, PAE is Å and may retain batch/BOS/EOS axes. No extra inference or rescaling occurs. Sequence-stage returned coordinates are labelled `returned_coordinates`: the service may decode coordinates even when no input coordinates were supplied; structure-stage coordinates are labelled `generated_structure`. The latter produces a completed mmCIF file when a canonical single chain has finite atoms at every position. Extended native sequences or positions without finite atoms remain in the native result and cannot be converted to the complete canonical structure format. Occupancy 1 and B_iso 0 are representation constants, distinct from native confidence.

## Implementations and defaults

`workbench.esm3.biohub` uses pinned `esm.sdk.client(model='esm3-open-2024-03', request_timeout=150)` and `client.generate(ESMProtein, GenerationConfig)`. Settings: `token` and optional `service_url` (default `https://biohub.ai`). The SDK owns retry handling: its default is at most five attempts for applicable 429/500/502/503/504 errors. The adapter adds no retries. Biohub exposes no seed control; supplying `seed` fails.

`workbench.esm3.local` uses the pinned native `esm3_sm_open_v1` builder, encoder, decoder and function decoder from the existing configured `model_path`. Settings also select `device` (`cpu` default, `cuda`, `mps`) and an existing `python` executable. Required assets are checked before loading; nothing is downloaded. A supervised subprocess owns the shared model lease, complete model lifetime and RNG. After loading, it calls `torch.manual_seed(seed)` and, for MPS, `torch.mps.manual_seed(seed)` before generation. `seed` defaults to the module's explicit literal `0`, accepted range `[0,2**63-1]`; zero is a deterministic seed. Each independent request uses the configured seed literally, so repeated samples may be equal. It has no sampling retry layer. Worker cancellation terminates inference and releases resources before returning.

Both adapters explicitly pass every `GenerationConfig` computation control:

| Control | SDK default |
|---|---|
| `num_steps` | 20 |
| `temperature` | 1.0 |
| `top_p` | 1.0 |
| `schedule` | `cosine` (`linear` also available) |
| `strategy` | `random` (`entropy` also available) |
| `temperature_annealing` | true |
| `invalid_ids` | empty list; users may configure native token IDs |
| `condition_on_coordinates_only` | true |
| `only_compute_backbone_rmsd` | false |

Defaults and native input semantics come from fixed `repositories/esm` commit `43b4548b86762edfa747b07d5f440aad3c33acee`: `esm/sdk/api.py`, `sdk/forge.py`, `sdk/retry.py`, `sdk/base_forge_client.py`, `utils/function/encode_decode.py` and `utils/constants/esm3.py`. Local loading follows `pretrained.py`; sampling follows `utils/generation.py`. Biohub's [HTTP snapshot](../../docs/biohub-api-reference/v1/endpoints/generate.md) lists temperature 0.5; this adapter explicitly sends the SDK default 1.0. It uses only fields forwarded by the selected `ESMProtein` SDK path. Model names, deployment paths and dependency constraints refer to the actual tools.

Local adapters acquire the [shared model resource](../../docs/local-models.md) themselves. Direct local node/adapter execution must not be nested inside another model-validation lease.
