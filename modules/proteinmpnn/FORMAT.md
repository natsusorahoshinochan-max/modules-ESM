# Backbone design results

The design node accepts one `workbench.structure_set` or `workbench.prediction`
package and reads each explicit object's `id` and `structure: {file, format}`.
Coordinate files contain exactly one model. Supported inputs and native constraint
positions are described in [TOOL.md](TOOL.md). It processes objects in package
order, with one complete tool request per backbone.

The `design` output uses `workbench.proteinmpnn_design`. Its JSON entry
contains `objects`; every generated object is a complete design sample with an
independently assigned `id`, optional `label`, and these fields:

- `chains`: actual chain name to complete native sequence, including fixed chains
  and supported native X residues. Each chain remains a separate molecule.
- `positions`: ordered `{chain, author_number, insertion_code, tool_position}`
  records. `tool_position` is 1-based within its chain; author numbering and insertion codes retain their
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

## Explicit chain sequence conversion

The design node delivers only `design`. To use a generated chain with a standard
sequence consumer, insert `workbench.proteinmpnn_chain_sequence`. Its `design`
input accepts one `workbench.proteinmpnn_design` package, and its `sequence` output
delivers the existing strict `workbench.sequence` format. Parameter `chain` names
one actual chain to select from every sample. It may be omitted only when every
sample has the same single actual chain. Multichain samples require an explicit
choice, including when only one chain was designed and the others were fixed.

Each selected sample chain becomes one new independently identified sequence
object in sample order. Its sequence is exactly that chain's sequence. Positions
follow the complete one-based `tool_position` mapping as `sequence_index`, retaining
the original `chain`, `author_number` and `insertion_code`. An optional label names
the sample and selected chain. The converter neither joins chains nor copies
whole-design scores onto the selected chain.

A missing chain, incomplete/ambiguous mapping, empty chain or selected noncanonical
symbol such as X fails the whole conversion before output. It never drops samples,
replaces residues, resamples or changes native tool parameters. The original rich
design remains available with all chains, native scores and files. X in an
unselected chain does not prevent converting a canonical selected chain.

The result viewer displays actual chains separately and can add this conversion
node bound to the explicitly viewed package. Connect its sequence output to a
sequence consumer, then save the canvas. For a connected flow, use
`design.design → chain.design` and `chain.sequence → prediction.sequence`.

Consumers read the design entry and its declared files directly. They need neither the
producer's Python implementation nor its original project or execution history.
