# Sequence and condition editing

Install `modules.sequence_edit:module`. The editor consumes
[`workbench.sequence`](../sequence_io/FORMAT.md#workbenchsequence), explicit
`workbench.structure_set`, `workbench.prediction` or
`workbench.structure_confidence` inputs, and its own `workbench.sequence_conditions`.
Structure processing is separately installable. Editing voluntarily imports its
public operations and `modules.structure_io.target`; both are provided by the
`protein-workbench` distribution with its declared Gemmi dependency.

## Complete target and explicit conditions

`workbench.sequence_conditions` has a JSON entry with `id`, current `sequence`,
ordered `positions`, `random_operations`, `target` and `conditions`. `target` is
`{file: "target.cif", format: "mmcif", chain: "A"}`. The target mmCIF contains the
complete current polymer, including positions with no atoms. Its one-based
`label_seq_id` is current target order; source author numbering and insertion
codes are retained independently. `_` in the editing sequence is `UNK`/`X` in
the standard target file. Inserting a position adds no coordinates.

`conditions.sequence` lists `{position, residue}` for fixed sequence positions.
`conditions.coordinates` lists `{position, atoms}` for coordinates selected as
conditions; `atoms` contains names such as `N`, `CA`, `C`. Both use the target's
one-based label positions. Actual coordinates are read from `target.file`, never
from JSON position rows. Unselected target atoms remain available. Clearing a
coordinate condition does not delete the target or original source structure.

Each `positions` row has an independently assigned editing `id`, `residue`,
`prompt` and boolean `fixed`. Prompt is the fixed residue or `_` for a variable
position. Optional `source`, `structure_position` and `target_author` record
explicit supplied correspondence. Position rows cover the full target in order.
The input is complete without producer history. Receivers validate their actual
operation's requirements and any consistency they depend on.

```json
{
  "id":"edited-object", "sequence":"A_C",
  "positions":[
    {"id":"a","residue":"A","prompt":"A","fixed":true},
    {"id":"new","residue":"_","prompt":"_","fixed":false},
    {"id":"c","residue":"C","prompt":"_","fixed":false}
  ],
  "random_operations":[],
  "target":{"file":"target.cif","format":"mmcif","chain":"A"},
  "conditions":{"sequence":[{"position":1,"residue":"A"}],
    "coordinates":[{"position":3,"atoms":["CA"]}]}
}
```

The package may retain `structures`, each with an independent record `id`, selected
`object`, source package `format`, retained `entry`, and `files` mapping source
keys to package keys. The original package files, full source structure, other
components and research files are copied. Each adoption has its own record;
selecting an existing record reuses it. Source object IDs may repeat across
records. These files remain usable after the source project is deleted.

## Establishing a template

`workbench.edit_sequence` and the `workbench.sequence_edit` interaction accept an
optional `source`. For sequences, select `object` when several objects are present;
without a package, provide `sequence`. Existing sequence-position correspondence
is carried with the resulting rows.

For a structure source, select `object` when several objects are present and
provide `selection: {chains: ["A"]}` or `selection: {positions: [...]}` using the
[structure module's real-position selection](../structure_io/FORMAT.md#public-structure-processing).
The selected amino-acid positions must belong to one chain. Optional `regions`
restricts the selection by author numbering, for example `12A,15:20,25:28`.
Ranges are inclusive; selected rows retain file order. Every requested region
must contain an actual position. The editor establishes correspondence itself.

`tracks` selects initial `fixed` sequence and/or `coordinates` conditions
(default both); an empty list creates a variable template without conditions.
Optional `atoms` selects condition atom names, default all actual atoms. Complete
target atoms and the full source remain preserved. Ambiguous alternate atom
locations require explicit structure preparation. No unrelated components are
silently selected into a protein template.

## Editing, preview and confirmation

An accepted editing package is the current base. Requests send that package and
the next `operation`; coordinates are reconstructed from its target file. Before
first acceptance, an inline `document` may retain IDs in a coordinate-free draft.
Inline coordinates, retained structures, or an inline document supplied alongside
an accepted editing package fail.

Operations are `insert` (gap index and sequence), `delete`, `update`, `reorder`
and `random_insert`. Position selections use current editing IDs. Updates support
`residue`, `prompt`, `fixed` and current coordinate conditions. Insertion assigns
new IDs, deletion removes positions and attached conditions, and reorder names
each current position once. Current target order and condition positions are
recomputed together. Setting coordinates accepts explicit named XYZ values;
clearing uses `coordinates: null` and stores no transform replay.

`random_insert` uses integer `seed`, `count`, inclusive current-gap `start`/`end`
and insertion `alphabet`. Gap 0 precedes the first position; gap N follows the
last. Python `random.Random(seed)` samples distinct gaps without replacement.
The read-only `random_operations` record stores parameters and actual gap,
resulting index, position ID and residue. Later edits preserve those actual
positions and never refill or resample the operation. New random edits use the
current content; identity allocation is independent of the RNG.

The editor previews actual results. Confirmation receives exactly that delivery
and atomically replaces the node's source binding and source connection. Cancel
restores the accepted state. Undo restores prior parameters, bindings, connection
and displayed state without replaying random operations. Confirmation and undo
mark the project unsaved; normal manual save persists workflow and layout.

## Local structure conditions

The optional `structures` port accepts structure sets and prediction packages.
`workbench.sequence_structure` selects either
`structure: {input: "structures", object: "id"}` or
`structure: {retained: "record-id"}` with the external port omitted. A read-only
request shows the full source atom view and current template.

`adopt_structure` takes explicit `mapping: [{edit_position, position}]` and
`tracks` selecting `coordinates`, `residue` and/or `fixed`; only these tracks and
positions change. `position` uses actual chain, author number and insertion code,
optionally model and component name. Optional `atoms` selects condition atom
names. This operation provides explicit local correspondence between independently
chosen inputs; initial chain/region template creation requires no mapping list.

`transform_coordinates` takes current position IDs, a proper 3×3 rotation and
three-value Å translation. It transforms current selected condition atoms;
unselected target atoms and original files stay intact. Clearing a condition
stops using it; setting another adopts the new values. Undo restores the prior
accepted package.

Preview display may use `document_file` and `view_file`, read through
`host.readPreviewFile(preview.id, "edited", key, {signal})`. `editor.json` is a
derived editor view, not the package entry or downstream scientific interface.
The viewer fits full source atoms and current conditions. Dragging selected
conditions previews XY translation immediately with fixed projection throughout
the gesture; release obtains the backend preview. One request owns its cancellation
signal and token through execution and file reading. Stale responses cannot
replace a changed project, node or draft. Confirmation transfers the token to the
host's guarded file receipt; cancellation releases it. Read-only inspection remains
available during a project run.

## Reusable template recipe

A node receiving a different structure on each call can save `operations`, an
ordered list of edits. `delete`, `update` and `reorder` may use `indices` instead
of editing IDs: these are one-based positions in the current target at that step.
Insertion `index` remains a zero-based gap. An interactive `operation` and a
saved `operations` list cannot be supplied together.

After those edits, optional `template_conditions` explicitly sets the entire
current template's conditions. `fixed_positions` and `coordinate_positions` are
required lists of one-based current target positions. Omitted positions are
variable and have no coordinate condition. Optional `atoms` chooses names from
the complete target's actual atoms; selecting an unavailable coordinate fails.
Each call resolves the recipe against its own input and current position order.
No condition or position identity is inherited from an earlier call.

```json
{
  "selection":{"chains":["A"]}, "tracks":[],
  "operations":[
    {"kind":"insert","index":11,"sequence":"__"},
    {"kind":"delete","indices":[27]}
  ],
  "template_conditions":{
    "fixed_positions":[1,2,3,4,5],
    "coordinate_positions":[1,2,3,4,5,31,32,33,34,35,36],
    "atoms":["N","CA","C"]
  }
}
```

The editor's reusable configuration panel saves these node parameters without
replacing the source connection. Its position fields accept comma-separated
numbers and inclusive colon ranges; the saved parameters contain explicit lists.
This allows a node inside a user-connected iteration to establish a fresh
editable template from each incoming result.
