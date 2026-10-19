# Public ESM3 generate tool

`workbench.esm3.generate` is a task-independent slot. Its Python declarations are `ESM3Request` and `ESM3Result` in [contract.py](contract.py). Third-party implementations depend only on that public contract and public runtime. The sequence task owns source interpretation, fixed positions, sample batching, identities, output encoding and continuation.

```python
generate(request: ESM3Request, parameters: dict, runtime) -> ESM3Result
```

`request.track` is the actual SDK output track (`sequence`, `structure`, `secondary_structure`, `sasa` or `function`). `request.tracks` contains explicit `sequence`/Prompt plus optional `secondary_structure`, `sasa`, `function_annotations`, `coordinates` and `potential_sequence_of_concern`. Sequence uses the native alphabet and `_` masks; `|` is the SDK chain separator. Aligned tracks have exactly the sequence string length. SASA accepts finite numeric values or `null`; local native calls additionally accept the fixed SASA tokenizer vocabulary tokens, passed unchanged. Coordinates are an ordered list of `null` or named-atom objects with finite XYZ triples in Å; only atom37 names are supported. They become native `[length,37,3]` tensors, with unspecified atoms represented by NaN. Unsupported atoms fail before calling the model. Function annotations are `{label,start,end}`, with inclusive one-based bounds; label support is checked by the selected native tool.

The adapter returns actual track values in `result.tracks` (coordinates are file-backed), a closed JSON `values_file` relative to `runtime.workdir`, effective `parameters`, and local `actual_seed` or remote `None`. The file holds all returned tracks and naturally returned metrics, as described in [FORMAT.md](FORMAT.md). It remains in the caller's workdir until host reception completes. The caller includes it in its Delivery. Errors raise with a concrete reason; SDK error values are failures. The adapter performs one SDK `generate` operation, keeping that SDK's applicable retry behavior. It does not generate object IDs or organize task continuation. A sequential caller can read the first call's native tracks and explicitly construct a second call; no paired-task state is hidden in the adapter.

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

## Public generation file helpers

`modules.esm3.generation` exports two concrete helpers used by sequence completion
and [sequence-then-structure generation](../joint_generation/FORMAT.md):

- `read_sources(package)` reads the public canonical sequence or current editing
  format, returning ordered records with `id`, current `prompt`, complete
  `positions`, and current named `coordinates` when provided. It does not replay
  edits or read retained source structures to replace current coordinates.
- `retain_result(result, request, source, ordinal, runtime, files)` checks an
  actual `ESM3Result`, complete native sequence and fixed Prompt correspondence,
  reads its closed native file, and adds that file to the task-owned Delivery
  file mapping. `ordinal` is zero-based within one input's samples. It returns
  `(object, native_document)` with the public generated object shape and an
  independently allocated object ID. The caller owns phase organization,
  task-specific output requirements, acceptance and continuation.

These helpers are installed with the `protein-workbench` distribution. They are
optional public code reuse; independently reading the documented file formats
requires no helper or producer installation.
