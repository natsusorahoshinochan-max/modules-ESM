# ESMC tools

Install `modules.esmc:module` through module management. The default official
installation enables it. Add `Represent sequence` on the canvas, bind an imported
or explicitly selected `workbench.sequence` package, and select the representation
tool. Node parameters select `embedding`, `logits` or `both` (default `both`) and
saved `float32` or `float16` (default `float32`). Inspect saved numeric pages in
`ESMC numeric values`; use package ZIP export for all values and parameters.

Environment configuration belongs in the ESMC module settings:

| Setting | Use |
| --- | --- |
| `model_path` | Existing local Hugging Face ESMC checkpoint directory |
| `device` | Explicit local `cpu`, `mps` or `cuda`; default `cpu` |
| `token` | Biohub credential, stored as a secret setting |
| `service_url` | Biohub service URL; default `https://biohub.ai` |

`workbench.esmc.local` uses the fixed esm native `EsmcForMaskedLM` loader with
`local_files_only=True` and the configured device at allocation time. It applies
the pinned `EsmcTokenizer` and performs inference without gradients. Existing
HF configuration and checkpoint files determine the model dimensions. It has no
additional computation parameters. Model files and runtime must already exist.

`workbench.esmc.biohub` uses fixed `ESMCForgeInferenceClient.encode` and `logits`.
Its `model` computation parameter is one of `esmc-300m-2024-12`,
`esmc-600m-2024-12`, or `esmc-6b-2024-12` (default). It requests precisely the
selected logits and/or service mean, retaining the SDK's five-attempt retry
policy and class default 60-second request timeout. SDK errors stop the operation;
the module adds no request retry layer. Dependencies are fixed in
[`pyproject.toml`](../../pyproject.toml) and [`uv.lock`](../../uv.lock).

The public `workbench.esmc.representation` tool slot receives
`represent(sequence, parameters, options)`. `sequence` is canonical protein text,
`parameters` are the selected tool's parameters, and `options.embedding` /
`options.logits` say which arrays are requested. It returns `tokens`, `mean`,
`logits`, `columns`, `mean_semantics`, `model` and resolved `parameters` as described in [FORMAT.md](FORMAT.md),
with unrequested arrays set to `None`. Arrays are finite floating point values;
missing requested arrays and invalid position axes fail. The node owns encoding
and completed output files. An Adapter owns its client/model resources and closes
them on success or error. Cancellation is checked between sequence requests.

Real checks use the machine-wide entry from [local models](../../docs/local-models.md):

```bash
.venv/bin/python -m protein_workbench_public.model_validation -- \
  .venv/bin/python -m modules.esmc.verify /private/path/esmc-config.json \
  --output /private/path/esmc-verification
```

The private JSON configuration contains `sequence`, `tool`, `parameters`, and the
module `settings` object above. Verification requests both actual arrays, commits
them through the public run, reopens storage and reads numeric pages. Use a private
output directory because module settings persist there. The current machine's 6B
validation uses Biohub; the exact local supplementary scope is maintained in
[the resource agreement](../../docs/local-models.md#资源受限机器的验证范围).
