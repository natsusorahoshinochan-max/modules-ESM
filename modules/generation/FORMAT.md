# Generation and design

Install `modules.generation:module` for scientific operation nodes, editors and result viewers. Independently install compatible tools: `modules.esm3:module` for local/Biohub multitrack generation, and `modules.proteinmpnn:module` for backbone design and scoring. Deployment settings belong to the selected tool; input interpretation and batch/phase organization belong to generation.

## Inputs and operations

**Complete or generate a conditioned sequence** (`workbench.complete_sequence`) and **Generate sequence then structure** (`workbench.joint_generation`) accept canonical `workbench.sequence` or the complete [editing target](../sequence_edit/FORMAT.md). Edited targets contain mmCIF with every target position and explicit sequence/coordinate selections. Additional aligned `conditions` are secondary structure, SASA, function annotations and the supported disclosure flag. Tool applicability is checked by its Adapter. Invalid conditions/overrides JSON remains an unsaved draft and blocks saving/running until corrected.

`samples` is a positive number per input, in input order then sample order. Joint generation performs a sequence call followed by a structure call using that accepted sequence and the original target conditions. `structure_parameters` explicitly overrides selected tool controls for the second call. Returned sequence-stage coordinates are input conditions; they are never silently substituted for the user's original target coordinates.

**Design sequences from backbone** (`workbench.design_backbone`) accepts explicit objects from `workbench.structure_set`/`workbench.prediction`, or `workbench.sequence_conditions`. Each object is one tool request. For an edited target, ProteinMPNN requires every target position to have canonical sequence, explicit unambiguous author chain/numbering and finite N/CA/C/O, and the coordinate selections must cover the entire backbone. Missing positions are rejected before model execution. Selected sequence residues become fixed positions; explicit native fixed positions are retained. Tool sampling count and every native parameter are described in [ProteinMPNN](../proteinmpnn/TOOL.md).

## Batches and continuation

An exhausted request failure stops unstarted requests. Accepted successful prefixes remain available for viewing/export, with an incomplete batch status; they do not automatically drive downstream nodes. Continue uses the original input, tool and parameters, skips accepted successes and returns cumulative results. Joint continuation retains an accepted sequence whose structure call failed and resumes that exact structure phase. File reception and phase progress commit together. Changes to the current canvas do not change an old run's continuation. Private continuation state is unnecessary for reading results.

## workbench.esm3_generation

The JSON entry contains `objects`, `batch: {completed,total,status}` and `tool: {id,parameters}`. An object has:

- Independently allocated `id`, complete native `sequence`, and ordered `positions` covering every output string position. Native extended residues and actual `|` separators remain intact.
- Each position has one-based `sequence_index`; optional `edit_position`, `source` and `structure_position` retain current input correspondence. Source residue chain/number/insertion code and generated file numbering have separate meanings.
- `generation: {input,sample,tracks}` identifies the explicit source, one-based sample and actual supplied tracks. Edited inputs additionally contain `target: {file,format,chain}` and `conditions`; the referenced complete target is included in the output package.
- `native: {file}` points to complete native tracks and natural metrics. The selected tool documents array axes and units; [ESM3 native values](../esm3/TOOL.md) preserve pLDDT/pTM/PAE without recomputation.
- `coordinate_role` distinguishes `absent`, `input_conditions` and `generated_structure`. Optional `structure: {file,format: "mmcif"}` is an Adapter-produced complete canonical structure; only generated structure output can contain it.
- `tool: {parameters,actual_seed}` records effective controls and actual seed. Credentials/deployment settings are excluded.

**Use a generated chain as sequence** (`workbench.esm3_sequence`) explicitly converts one actual chain. Select zero-based `chain_index` for multiple `|`-separated chains; a single chain may omit it. The selected chain must contain the 20 canonical amino acids. Conversion assigns a new identity and retains available real-residue correspondence. It does not rewrite extended residues or join chains.

## workbench.joint_generation

The entry contains completed `objects`, optional `pending_sequence`, `batch: {completed,sequence_completed,total,status}` and `tool: {id,parameters,structure_parameters}`. Completed objects follow the generation shape above, with `sequence_stage` containing the exact successful sequence object and `generation.sequence_object` identifying it. Their native file is the actual structure phase output. Natural metrics remain attached to the phase that produced them.

**Select a joint generation phase** (`workbench.joint_to_esm3`) requires `stage: "sequence"` or `"structure"` and emits `workbench.esm3_generation`. Sequence selects completed first stages plus any pending accepted sequence; structure selects completed samples. No available result is an error. All source files and the source manifest remain included; no inference occurs.

**Use generated structure coordinates** (`workbench.joint_structure`) reads the Adapter-produced ordinary structure file, without decoding native atom axes. Choose explicit `chain` and integer `start_number`. It produces `workbench.structure_set`, retaining the generated object ID, complete `source_object`, original files and `source_manifest`. `native_positions` maps each current sequence position and original correspondence to the chosen output chain/residue number. A noncanonical/multichain native sequence, missing Adapter structure, or incomplete correspondence fails explicitly. Use the structure module to view or export PDB/mmCIF.

## workbench.proteinmpnn_design

The entry contains `objects`, `tool: {id,parameters}` and `batch: {completed,total,status}` counting backbone requests. Each sample has an independent `id`, optional `label`, and:

- `chains`: every actual chain's complete native sequence, including fixed chains and supported X.
- `positions`: ordered `{chain,author_number,insertion_code,tool_position}`; tool positions are one-based consecutive chain positions, preserving real numbering and insertion codes separately.
- `backbone`: the explicit source object, with all source package files included. This is the input backbone, not a predicted structure of the new sequence.
- `design`: actual `score`, `global_score`, per-chain `residue_nll`, `design_mask`, `coordinate_mask`, plus any returned `temperature`, `batch_index`, `recovery`, `tool_chain_order` and `sampling_probabilities`.
- `tool: {parameters,actual_seed}`: effective controls and actual seed for that backbone.

NLL uses natural logarithms. `score` averages residue NLL over coordinate-valid × designed-chain × nonfixed-position mask. `global_score` averages over the coordinate mask across all chains. Lower is better. `recovery` is agreement with the original backbone sequence over the design mask. Sampling probabilities retain actual arrays and alphabet columns `ACDEFGHIKLMNPQRSTVWYX`. Independent sequence/backbone scoring is a separate operation with explicitly supplied objects.

**Use one design chain as sequence** (`workbench.proteinmpnn_chain_sequence`) chooses actual `chain` from every sample. It may be omitted only when all samples share the same single chain. The output creates independent canonical sequence objects, retains complete real residue mapping and optional labels, and does not copy whole-design scores onto a chain. Missing chains, ambiguous mappings or noncanonical selected residues fail. The result viewer can add this converter bound to the explicitly viewed package.

All formats include referenced files. An independent consumer can read the manifest and files through public package access after adoption, source project deletion and producer uninstall.

Sequence conversion preserves available source author and label correspondence
using the [sequence format](../sequence_io/FORMAT.md#workbenchsequence). A source
polymer position with a known label and unknown author number retains that label;
a newly inserted position without source correspondence keeps its sequence index.
