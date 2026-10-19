# Sequence then structure generation

Install `modules.joint_generation:module` and select an implementation of the
public [`workbench.esm3.generate`](../esm3/TOOL.md) slot. The official local and
Biohub implementations are supplied by `modules.esm3:module`. The Python helpers
used by both tasks are shipped by the `protein-workbench` distribution; that
installation dependency supplies the public `modules.esm3` contract. Reading the
files independently needs no producer installation.

**Generate sequence then structure** accepts canonical `workbench.sequence` or
current [`workbench.sequence_conditions`](../sequence_edit/FORMAT.md). It submits
the current ordered Prompt, fixed/variable positions and named-atom coordinates.
Additional aligned `conditions` are `secondary_structure`, `sasa`,
`function_annotations` and `potential_sequence_of_concern`, with the exact public
tool semantics. Unsupported inputs fail with a specific reason.

Each sample performs two dependent calls: generate the sequence, then generate
structure using that successful sequence and the same original current
conditions. Coordinates in the second request are those explicitly supplied by
the user, rather than decoded replacements from the sequence call. No prior
editing operation is replayed. Tool controls apply to both phases;
`structure_parameters` explicitly overrides individual controls for the second
call. Each call records its effective controls. Defaults, supported controls,
backend limitations and seed semantics are maintained in [TOOL.md](../esm3/TOOL.md).
Local seed, including zero, is passed literally to each call. Biohub accepts no
seed. Invalid JSON conditions or overrides remain local unsaved drafts and block
saving and running until corrected.

`samples` is the positive number of independent samples per input, in source
order then sample order. An exhausted failed call stops all unstarted calls.
Accepted complete samples remain available; a successful sequence whose structure
call failed is also retained. Continue uses the original input, tool and controls,
skips complete samples, and reuses that exact accepted sequence for its pending
structure call. It returns cumulative results. File reception and phase progress
commit together; failed reception leaves the preceding accepted progress intact.
Failed partial results require explicit selection as historical input before
further use.

## workbench.joint_generation

The JSON entry has:

- `objects`: ordered complete sequence-and-structure samples.
- `pending_sequence`: one successful sequence object awaiting structure, or `null`.
- `batch`: `completed` complete samples, `sequence_completed` accepted sequence
  phases, `total` requested samples and node `status`.
- `tool`: selected implementation `id`, supplied `parameters` and explicit
  `structure_parameters`; deployment settings and credentials are excluded.

Objects use the [public native ESM3 object shape](../esm3/FORMAT.md#workbenchesm3_generation):
independent `id`, complete native `sequence`, ordered `positions`, actual input
`generation`, `native.file`, and effective `tool.parameters` / `tool.actual_seed`.
Each complete object additionally contains its successful sequence object as
`sequence_stage`; `generation.sequence_object` names that object's actual ID.
The complete object's native file is the structure call's actual output. Its
`generation.tracks` contains the successful sequence and original conditions
actually sent to that call. Each stage's natural metrics belong to that stage's
actual generation/reconstruction.

Positions retain current editing identities, complete source correspondence and
separate actual `structure_position` when supplied. Native extended residues and
chain separators remain intact. Native files contain complete returned `tracks`
and natural `metrics`; atom37 coordinates, missing coordinates as `null`, metric
axes and scales follow the public ESM3 format. Structure success requires actual
atom37 arrays with finite coordinates present. Missing atoms remain missing.
No confidence or absent atom coordinates are manufactured.

Every referenced native file is included. Manifest and native files can be read
through the public `Package.open` interface after cross-project adoption,
source-project deletion and producer uninstall. Continuation state is unnecessary
for reading results. The viewer distinguishes complete samples and a pending
structure phase, displays positions and actual controls, and plots the finite
native atom coordinates in an XY view. Full native values are retained in files
and ZIP export.

## Explicit phase conversion

**Select a joint generation phase** (`workbench.joint_to_esm3`) requires
`stage: "sequence"` or `stage: "structure"` and emits
`workbench.esm3_generation`. Structure selects only complete samples; sequence
selects each complete sample's actual first stage and any accepted pending
sequence. A stage with no successful results fails. The conversion retains all
native source files and the original manifest under `source_manifest`, and
records `stage`. It performs no generation, metric calculation or chain change.

The existing **Use a generated chain as sequence** node is an explicit next step
for canonical sequence consumers. It requires chain selection for multichain
results and rejects extended symbols. Native structure and scores remain in the
source package. Consumers of the native format can read actual scalar natural
metrics directly; arrays keep their documented native axes and require an
explicit appropriate analysis before use as a scalar.
