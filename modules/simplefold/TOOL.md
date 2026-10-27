# SimpleFold prediction tool

`modules.simplefold:module` independently implements the [public prediction slot](../folding/TOOL.md) as `workbench.simplefold.local`. Install the module and select its tool on the prediction node. Model resources and the existing Python interpreter are configured in module deployment settings; no resources are downloaded.

The Adapter invokes pinned Apple SimpleFold (`c7a5570`) in an isolated process, with the existing Facebook ESM source and ESM2 checkpoint. It supports a single canonical protein chain and returns one structure. Torch uses CUDA when available, otherwise CPU. Structure or ligand conditioning and multiple samples are outside this slot's current request/result cardinality.

Parameters follow the upstream CLI: `simplefold_model` (100M, 360M, 700M, 1.1B, 1.6B, 3B), `num_steps` (default 500), `tau` (default 0.1), `seed` (default 42), `plddt` (default false), `output_format` (default mmcif; pdb also supported). `log_timesteps` defaults true and controls the upstream sampler directly. The public declaration lists exact model identifiers and accepted values. Seed 0 is passed unchanged. No ESMFold2 parameters are accepted.

Optional pLDDT loads the 1.6B latent model and confidence head and exports their actual residue values on the prediction format's 0–1 scale. Without pLDDT, confidence is omitted; the upstream structure writer's default B-factor is never interpreted as confidence. SimpleFold supplies no pTM. The shared machine validation runner holds the resource lock throughout local model loading, inference and process cleanup; do not wrap this Adapter in another runner.

Required deployment paths are `model_path`, `esm2_source`, `esm2_checkpoint` (with its adjacent contact regression checkpoint), and `ccd_path`. `python` selects an existing interpreter with pinned dependencies. Missing files, unsupported parameters and upstream failures stop the prediction with a diagnostic.

## Existing-geometry confidence

`workbench.simplefold.confidence` implements the public
`workbench.evaluate.structure_confidence` slot from
[`modules.structure_confidence.contract`](../structure_confidence/FORMAT.md).
`modules.simplefold.confidence.create(settings)` is the reusable public caller;
the bundled `protein-workbench` distribution supplies its contract and structure
reader code. Deployment settings are the same existing Python, model directory,
Facebook ESM source root, ESM2 checkpoint/contact-regression and CCD pickle paths
as prediction. Required checkpoints are `simplefold_1.6B.ckpt` and `plddt.ckpt`.
It never downloads resources. There are no node sampling parameters for this
method: latent model, time 1, processor coordinate scale 16, reference scale 5,
ESM2-3B features and the pLDDT head define the calculation.

The Adapter reads the given PDB/mmCIF, requires one conformation and canonical
protein residues with every heavy atom in the upstream reference atom set.
Unrepresented atoms (including hydrogen and terminal OXT), missing reference
atoms, alternate locations, nonprotein components and ambiguous residue mapping
fail explicitly. All selected-object components are checked, even for a reported
region. Atom names and elements establish a complete projection; original
coordinates are explicitly placed into the tool's atom order, including symmetric
atoms that its parser may reorder. The original file remains unchanged.

The fixed upstream Boltz featurizer translates coordinates by their resolved-atom
centroid and pads atom tensors. The processor divides coordinates by 16 and
reference positions by 5, then constructs ESM2 features. ESM2 is released before
loading the latent model and head. At time 1 the 1.6B model reads the given
normalized geometry; only its latent enters the pLDDT head. No sampler or
structure-generation path runs. Values are the head's bin-center expectation on
0–1, the same numeric scale before upstream inference display multiplies by 100.
They are model-predicted local confidence for the supplied geometry; there is no
experimental lDDT reference in this operation.

Interface basis: pinned SimpleFold
`utils/mmcif_utils.py:parse_mmcif`, `boltz_data_pipeline/tokenize/boltz_protein.py`,
`boltz_data_pipeline/feature/featurizer.py`,
`processor/protein_processor.py:preprocess_inference`,
`model/torch/architecture.py:FoldingDiT.forward`,
`model/torch/confidence_module.py:ConfidenceModule.forward`, and
`inference.py:generate_structure`'s separate latent/head calls. Existing-geometry
execution uses the same supervised machine resource lease as prediction; do not
wrap the caller in a second model-validation lease.
