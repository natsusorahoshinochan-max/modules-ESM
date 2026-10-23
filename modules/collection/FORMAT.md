# Object collections

Install `modules.collection:module` from the `protein-workbench` distribution.
Collection operations assemble explicitly supplied objects and their required
files. Filtering policy belongs to [filtering](../filtering/FORMAT.md).
React 19 comes from the public UI runtime. Structure extraction voluntarily uses
the public `modules.structure_io.parse` / `atoms` functions; sequence extraction
uses `modules.sequence_io.formats.read_sequences` for the promised sequence format.
The source producer does not need to be installed or enabled.

## Nodes and ports

| Node | Input | Output | Parameters |
|---|---|---|---|
| `workbench.collection.merge` | `packages`, many | `collection`, one | None; preserve package/item order |
| `workbench.collection.split` | `collection`, one | `items`, many | None; one object per output package |
| `workbench.collection.select` | `collection`, one | `collection`, one | `items`: distinct zero-based item positions in desired output order |
| `workbench.collection.extract_structures` | `collection`, one | `structures`, one `workbench.structure_set` | None |
| `workbench.collection.extract_sequences` | `collection`, one | `sequences`, one `workbench.sequence` | None |

All `collection` and `items` ports use `workbench.collection`. Merge accepts this
format plus `workbench.sequence`, `workbench.structure_set`, `workbench.prediction`,
`workbench.comparison`, `workbench.proteinmpnn_design`, `workbench.esm3_generation`,
`workbench.structure_confidence`, `workbench.solubility` and
`workbench.sequence_backbone_evaluation`. A comparison contributes its subject;
a sequence/backbone evaluation contributes each entire explicitly evaluated joint
sequence context. Joint contexts are kept together, preserving the meaning of their
scores. Only explicitly supplied objects participate; merging does not deduplicate
objects or choose newer evaluations.

Empty merge produces an empty collection; splitting it yields zero packages.
The collection viewer can create selection, splitting, structure extraction and
sequence extraction nodes. The selection editor shows labels and output order;
users do not enter object identities. Changes remain canvas drafts until saved.

To process each object in a subflow: merge desired inputs, split to `items`, bind
those packages to the subflow's many input, then explicitly extract the format
needed by its scientific operation. Merge the delivered output packages when
selection should apply across the whole batch. The carrier never unpacks objects.

## workbench.collection

The JSON entry contains ordered `items`, `sources`, `selected` and `parameters`.
Each item is `{object: <complete original object>, source: <source index>}`.
Joint items retain the complete original `members`. Scientific object identities
are unchanged. `selected` contains the invocation's input/item positions for
explanation; independent consumers use `items` and its source maps.

Each source has an independently allocated ordinary `id`, original `format`,
original `entry`, `files` mapping original keys to package keys, and `roles`
(`candidate` and/or `evaluation`). Every original file is included, including
manifests, coordinate files, numeric/native output and research files. Resolve
original object and source-manifest references through that source's map.

Splitting, selecting and filtering preserve source identities. Merging packages
that explicitly retain the same source identity records that source once, keeping
one evaluation context after a split/rejoin. Different source identities remain
distinct even if their files happen to have the same contents. No content digest,
input-equivalence lookup or scientific identity rewrite is used. Source maps are
flattened during assembly; consumers do not need earlier collection packages.

`modules.collection.formats.read_collection(package)` and `SourcePackage(package,
source)` are optional standard-library public readers. `SourcePackage` offers the
original file keys through read-only `open`, resolving each through the explicit
file map. Adopted collections remain usable after source deletion and producer
uninstall. Consumers can instead implement the file contract independently.

## Explicit structure and sequence extraction

Structure extraction requires a complete PDB/mmCIF descriptor for each selected
object and exactly one conformation in each file. It includes unchanged coordinate
bytes and an atom-view JSON generated from those actual bytes; water, ligands and
other components remain. Output objects preserve identity, optional label,
sequence and positions. `collection_source` contains the original object and its
format/entry/file map; the complete original source files are included. A native
sequence-only or joint context without one complete structure cannot be extracted
as a structure. Extraction never treats input coordinate conditions as a generated
structure.

Sequence extraction requires a nonempty selection of distinct objects with complete
single-chain canonical sequences. Multi-chain or extended native sequences require
their explicit chain conversion first. The output contains only the published
sequence fields: identity, sequence, optional label, text source and ordered
sequence positions. Existing author numbering/insertion correspondence is retained
when explicitly supplied in those positions or their native `source.position`.
This correspondence describes the supplied source, not newly assigned structure
numbering. The original collection remains independently available for native
tracks, evaluations and files outside the sequence format.
