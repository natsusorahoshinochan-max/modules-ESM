# Structure prediction tool slot

`modules.folding:module` provides node `workbench.predict`, which declares local slot `predictor` with public contract id `workbench.predict.structure`. An independently installed module supplies a public `Tool` with that slot id. Its `create(settings)` factory receives its own module's deployment settings and returns `predict(request, parameters, runtime)`. The host discovers matching declarations and injects the user's explicit selection in `Call.tools`.

The request is `modules.folding.contract.PredictionRequest(sequence, object_id)`. The result is `PredictionResult(structure_path, structure_format='pdb', plddt=None, ptm=None, extras={})`. An implementation importing these public dataclasses declares the prediction package as an installation dependency. It may produce PDB or mmCIF; sequence order must agree with the single protein chain. Any unsupported input or missing required result raises a descriptive exception. Tool-specific parameters are a separate dictionary and never inferred from another tool's names.

Write structure output completely inside `runtime.workdir`, close it before returning, and return its relative path. The prediction node owns subsequent encoding and passes its files to the host; the adapter relinquishes write ownership on return. No external paths or live streams are returned. Check `runtime.cancelled` before loading or starting requests and during cancellable waits. A cancelled call does not publish a successful prediction. This single-request node has no continuation state; failed requests use a new run.

## ESMFold2

The pinned SDK source is `Biohub/esm` commit `43b4548b86762edfa747b07d5f440aad3c33acee`; local model integration uses pinned `Biohub/transformers` commit `ef32577f55da19a4989cd7b22e004dc43a4998cb`. Local defaults follow `ESMFold2InputBuilder.fold`: 20 loops, 200 sampling steps, seed null, LM dropout 0.3, mask null, MSA depth 1024 and column mask 0.1. Noise scale, step scale and maximum inference sigma default to checkpoint configuration. Exactly one diffusion sample is requested for this node's single-structure output.

Remote defaults follow `FoldingConfig`: 20 loops, 100 sampling steps, dropout 0.3, mask null, MSA depth 1024, column mask 0.1, extra-output flags false, model `esmfold2-fast-2026-05`. Full `esmfold2-2026-05` is selectable. Null LM mask delegates the SDK's model-specific default (fast 0.1, full 0.0); the official HTTP field table and explanation differ, as recorded in `docs/biohub-api-reference/v1/endpoints/fold.md`. Remote seed is rejected. SDK default request retry settings are retained. The pinned SDK rejects `include_distogram` on both folding routes, so the Adapter reports it as unsupported. PAE, pair-chain iPTM and embedding output switches use the supported SDK controls.

Both adapters accept an optional `msa` dictionary with aligned `sequences` and optional `deletions`, translated to the official SDK MSA object. Existing MSA data is passed unchanged; the adapter does not generate alignments. Local seed, including zero, goes directly to the SDK. Native confidence values remain 0–1.

Configure existing Python executable, model directory, ESMC 6B directory and device in module settings for local use. The worker runs offline and explicitly attaches the configured ESMC path; it installs or downloads nothing. Local inference is supervised by `protein_workbench_public.model_validation` from before SDK/model loading through worker process cleanup. Remote settings are `token`, optional `service_url` (default `https://biohub.ai`) and request timeout (default 150 seconds).

## Executable verification

Copy `sample/local-verification.json` outside the repository and replace its paths with existing resources. From the installed application environment run:

```bash
python -m modules.folding.verify /path/to/config.json --output /path/to/new/verification-storage
```

The local Adapter already acquires the shared machine lock. Run this command directly to avoid nesting the same lock. The command performs actual sequence upload, public selection/injection, inference, package encoding, storage commit and independent structure-file parsing. A remote configuration selects `workbench.esmfold2.remote`, provides module settings with a previously configured token and removes seed. Do not include credentials in validation records.
