# Backbone design results

The design node accepts one `workbench.structure_set` or `workbench.prediction`
package and reads each explicit object's `id` and `structure: {file, format}`.
Coordinate files contain exactly one model. Supported inputs and native constraint
positions are described in [TOOL.md](TOOL.md). It processes objects in package
order, with one complete tool request per backbone.

The `design` output uses `workbench.proteinmpnn_design`. Its JSON entry
contains `objects`; every generated object has an independently assigned `id`,
`sequence`, optional `label`, and these additional fields:

- `chains`: actual chain name to complete sequence, including fixed chains.
- `positions`: ordered `{chain, author_number, insertion_code, tool_position}`
  records. The concatenated sequence follows this order. `tool_position` is
  1-based within its chain; author numbering and insertion codes retain their
  separate actual values. Chain sequence positions are consecutive in coordinate
  file residue order. Numbering gaps do not create invented residues.
- `backbone`: the original explicit structure object. Every original package file
  is included with its original file key, including source research files and
  atom correspondence. This refers to the design input, not a predicted structure
  of the generated sequence.
- `design`: actual tool result with complete chain sequences, scalar `score` and
  `global_score`, per-chain actual `residue_nll`, `design_mask`, `coordinate_mask`,
  and any returned `temperature`, `batch_index`, `recovery`, `tool_chain_order`
  and `sampling_probabilities`. Sampling probabilities use the alphabet columns
  `ACDEFGHIKLMNPQRSTVWYX`; these optional values are actual arrays when present.
- `tool`: effective tool `parameters` and `actual_seed` used for that backbone.

`residue_nll` contains negative log likelihood in natural logarithm units at each
mapped position. `score` averages it over `design_mask`, the product of native
coordinate validity, designed-chain selection and nonfixed-position selection.
`global_score` averages over `coordinate_mask`, covering all complete backbone
positions, including fixed chains and fixed positions. Lower NLL is better.
`recovery` is the design-mask fraction matching the original backbone sequence.
Native sample scoring uses the sampling call's actual decoding order. These
natural design scores remain with their generated objects; independent scoring
is a separate task using an explicitly supplied sequence and reference backbone.

The entry also contains `tool: {id, parameters}` recording the selected tool and
original user parameters, and `batch: {completed, total, status}` counting backbone
requests. A failed or cancelled batch retains accepted successful objects and
marks its incomplete status. It stops unstarted backbones. The host exposes these
partial packages for reading and ZIP export and blocks automatic downstream use.
Explicit continuation uses the original saved call, skips completed backbones,
and returns a cumulative complete package. Module-private continuation contains
only the completed backbone count and fixed random seed proposals; it is not
needed to interpret the output. Files and progress commit together through the
host, so failed delivery cannot advance completion.

The separate `sequence` output contains the same object IDs and sequences in strict
`workbench.sequence` format: exactly an `objects` array, each with `id`, `sequence`,
optional `label`, and `positions` containing one-based `sequence_index`, `chain`,
`author_number` and `insertion_code`. It is directly accepted by existing sequence
consumers. Select `design` for natural scores, tool positions and backbone files.

Consumers read the design entry and its declared files directly. They need neither the
producer's Python implementation nor its original project or execution history.
