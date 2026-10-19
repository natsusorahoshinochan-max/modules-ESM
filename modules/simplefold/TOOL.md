# SimpleFold prediction tool

`modules.simplefold:module` independently implements the [public prediction slot](../folding/TOOL.md) as `workbench.simplefold.local`. Install the module and select its tool on the prediction node. Model resources and the existing Python interpreter are configured in module deployment settings; no resources are downloaded.

The Adapter invokes pinned Apple SimpleFold (`c7a5570`) in an isolated process, with the existing Facebook ESM source and ESM2 checkpoint. It supports a single canonical protein chain and returns one structure. Torch uses CUDA when available, otherwise CPU. Structure or ligand conditioning and multiple samples are outside this slot's current request/result cardinality.

Parameters follow the upstream CLI: `simplefold_model` (100M, 360M, 700M, 1.1B, 1.6B, 3B), `num_steps` (default 500), `tau` (default 0.1), `seed` (default 42), `plddt` (default false), `output_format` (default mmcif; pdb also supported). `log_timesteps` defaults true and controls the upstream sampler directly. The public declaration lists exact model identifiers and accepted values. Seed 0 is passed unchanged. No ESMFold2 parameters are accepted.

Optional pLDDT loads the 1.6B latent model and confidence head and exports their actual residue values on the prediction format's 0–1 scale. Without pLDDT, confidence is omitted; the upstream structure writer's default B-factor is never interpreted as confidence. SimpleFold supplies no pTM. The shared machine validation runner holds the resource lock throughout local model loading, inference and process cleanup; do not wrap this Adapter in another runner.

Required deployment paths are `model_path`, `esm2_source`, `esm2_checkpoint` (with its adjacent contact regression checkpoint), and `ccd_path`. `python` selects an existing interpreter with pinned dependencies. Missing files, unsupported parameters and upstream failures stop the prediction with a diagnostic.
