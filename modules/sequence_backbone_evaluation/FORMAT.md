# Independent sequence / backbone evaluation

Install `modules.sequence_backbone_evaluation:module` and add **Evaluate sequence
against backbone**. The node takes exactly one `sequences` package
(`workbench.sequence`, `workbench.proteinmpnn_design`, or
`workbench.sequence_backbone_evaluation`) and one `reference` package
(`workbench.structure_set`, `workbench.prediction`, or
`workbench.structure_confidence`). Bind actual delivered packages; an unavailable
connected input must first be produced and explicitly selected.

In the node editor, **Inspect sequence and reference inputs** reads only these
packages through the public `workbench.sequence_backbone.inspect` interaction.
Choose the reference object and a complete sequence for every reference chain.
For a design object, select its actual source chain. The editor shows sequence
lengths, chain names and author-number/insertion-code positions. Choosing a source
accepts whole-chain, sequence-order correspondence to those displayed reference
residues. Incompatible lengths cannot be selected. Existing source correspondence
is preserved separately. No internal object identifiers or mapping JSON are
required in this interaction.

The parameters contain `reference` (the selected object identity), `bindings`
(one entry per reference chain), and optional `region` (actual reference
positions). A binding has `reference_chain`, selected sequence `object`, optional
`source_chain` for a multichain design, and complete ordered `positions`:
`{sequence_index, chain, author_number, insertion_code}`. `sequence_index` is
1-based within the selected sequence or source chain. Every reference chain and
every sequence residue must be covered exactly once in chain order. Missing,
ambiguous, partial or incorrectly numbered correspondence fails before scoring.
The node never retains a native sequence tail, joins chains or fills an omitted
context chain from the reference sequence. To evaluate a complex, supply complete
sequences for all its chains. Unsupported components or incomplete backbone
coordinates fail at the selected tool boundary.

Select `workbench.proteinmpnn.local` and configure its existing resources in
ProteinMPNN module settings. This task voluntarily reuses
`modules.proteinmpnn.contract.MPNNRequest/MPNNResult` and
`modules.structure_io.parse`; its Python installation dependency is the
`protein-workbench` distribution containing those public APIs and its pinned
gemmi dependency. React 19 is supplied through the public host interface.
Tool parameters and supported full-backbone input limits are maintained in the
[ProteinMPNN public call](../proteinmpnn/TOOL.md#public-reusable-call).
`seed=0` selects a random actual seed; positive seeds pass directly. Native scoring
repeats use `num_seq_per_target` and exact `batch_size` divisibility. Sampling
controls such as temperature affect design, while score mode performs only the
native forward evaluation. This task makes one complete-context score request;
it adds no prediction, generation or retry step.

## Result files

The `evaluation` port delivers `workbench.sequence_backbone_evaluation`. Its JSON
entry preserves the source sequence document and all original objects, including
existing natural design scores and generation relationships, and appends a record
to `evaluations`. Every source package file remains with its original file key.
The new entry has a fresh file key, so the original manifest also remains intact.
Every reference package file is copied under a fresh explicit prefix, with
`reference_manifest: {file, files}` recording the original-entry key and the
complete original-key → output-key map. That source manifest and
`reference.original_object` retain their original file keys; resolve them through
this map. `reference.structure.file` already points to the copied output key.
The complete structure and original research files remain available when a region
is selected.

An independent record contains:

- `origin: "independent_sequence_backbone"`, evaluated `object_ids`, the selected
  `reference` object, complete `bindings`, and full reference `positions`.
- Each reference position is `{chain, author_number, insertion_code,
  tool_position}`. Tool positions are consecutive 1-based indices within each
  actual chain in coordinate-file residue order. Numbering gaps add no residues;
  insertion-coded residues have separate positions.
- `region`: null for all reference residues, or an explicit nonempty list of
  `{chain, author_number, insertion_code}`; discontinuous chains/regions are
  supported. It selects reported values from the same full-context evaluation.
- `method: "ProteinMPNN score_only"`, selected `tool`, effective `parameters`,
  original `requested_parameters`, and the actual integer `actual_seed`.
- `unit: "negative log likelihood (natural logarithm)"` and `meaning` describing
  the scalar values. Lower NLL is better.
- `samples`, one actual result per requested stochastic decoding evaluation.
  Each contains unchanged full `chains`, per-chain `residue_nll`, `design_mask`
  and `coordinate_mask`, plus scalar `score` and `global_score`. Optional native
  fields such as `tool_chain_order` and `batch_index` remain intact.

`score` is native mean NLL over the product of coordinate validity, designed-chain
selection and nonfixed-position selection; the forward call uses the selected
chain × nonfixed-position mask. `global_score` averages over coordinate validity
for all supplied chains, including fixed ones. `region_mask` selects the explicit
reference region, and `region_nll` averages the actual per-position NLL over that
mask independently of the design mask. A region can therefore include fixed
positions. Changing native masks can change decoding context as well as the
reported native mean. Original raw values and all three masks are preserved.

The result viewer shows sequence objects, the chosen reference, actual method,
seed, scalar results and per-residue values/masks. Use the host's normal save,
ZIP and cross-project adoption operations. The package contains all its data;
source projects and installed producer modules are unnecessary for file reading.
An independent consumer reads the JSON entry and declared files directly. The
optional standard-library reader
`modules.sequence_backbone_evaluation.formats.read_evaluations(package)` checks
its current object/reference/position/value correspondence without invoking a
tool or consulting generation history.
