# Protein Studio

Install `modules.sequence_edit:module`. Studio supplies the `workbench.edit_sequence`
node and a full editing workspace. Structure processing remains separately
installable; Studio explicitly reuses its public operations and target mmCIF
writer. The `protein-workbench` distribution declares the Gemmi dependency.

## Prepared protein data

The `edited` output uses `workbench.protein`. Its JSON entry has an `id`, ordered
`positions` and `tracks`. Every position has a stable `id`; optional `source`,
`structure_position` and `target_author` retain explicit correspondence. Scientific
values occur only in `tracks`:

```json
{
  "id":"protein-1",
  "positions":[{"id":"p1"},{"id":"p2"},{"id":"p3"}],
  "tracks":{
    "sequence":["A",null,"C"],
    "coordinates":[{"N":[1,2,3],"CA":[2,3,4]},null,null],
    "secondary_structure":[null,"H","H"],
    "sasa":[12.5,null,31.0],
    "function_annotations":[{"label":"binding","start":2,"end":3}]
  },
  "target":{"file":"target.cif","format":"mmcif","chain":"A"}
}
```

All four position-wise arrays have the same nonzero length. Sequence values are
single uppercase amino acids or null. Secondary structure uses DSSP8 letters
`GHITEBSC` or null. SASA uses nonnegative finite square-angstrom values or null.
Coordinates are named atoms with finite XYZ values in angstroms; null has no
coordinates. Function annotation intervals use inclusive one-based current
positions and nonempty labels. Annotation labels remain editable text; each
consumer validates whether its tool supports them.

Each track contains its actual values and blanks. There are no editing permission
flags, fixed/variable masks, Prompt copies, or cross-track edit boundaries.

Studio emits `target.cif` as a standard representation of the current polymer and
actual coordinate values. Positions with missing sequence use `UNK`/`X` in this
file; positions without atoms remain in the polymer sequence. The public JSON
preserves null separately from an actual `X`. Current label positions follow the
edited order; source author correspondence remains explicit. Readers accepting
`workbench.protein` may consume the prepared tracks without a target file. When a
target is supplied, its sequence and atoms must agree with those values.

## Independent track outputs

Every execution emits `edited` and five single-package track outputs. All refer to
the same confirmed object ID and the same ordered positions:

| Port | Format | Content |
| --- | --- | --- |
| `sequence` | `workbench.sequence` | Single-letter sequence; `_` is an unfilled position |
| `coordinates` | `workbench.coordinates` | Named atoms and XYZ values in Å, or null |
| `secondary_structure` | `workbench.secondary_structure` | DSSP8 letter or null per position |
| `sasa` | `workbench.sasa` | Nonnegative finite area in Å², or null per position |
| `function_annotations` | `workbench.function_annotations` | Label intervals with inclusive one-based bounds |

Sequence uses the [sequence format](../sequence_io/FORMAT.md). Each other JSON
entry is `{"objects":[{"id":"protein-1","positions":[...],"values":[...]}]}`.
Positions use the sequence format's `sequence_index`, stable `id` and optional
source author/label correspondence. Per-position values include every position;
annotation values use `{label,start,end}` intervals instead. Entirely blank tracks
remain available. `modules.sequence_edit.tracks.read_track(package, track)` is the
public reader for these formats; consumers can also implement the documented
format independently.

Coordinates additionally carry `residues`, an aligned single-letter/null list for
atom identity, and `structure:{file,format:"mmcif"}`. The file uses chain A and
current positions 1…N for both author and label numbering. Missing atoms stay
absent. Original author numbering remains in `positions`; it must not be used as
the numbering of this current-coordinate file. `atoms` references the display
array. Structural consumers verify that the file agrees with the declared current
atoms and residues. Residue identity needed to interpret atoms does not implicitly
supply a sequence condition to generation.

Folding consumes `sequence` and checks its own alphabet/completeness. Generation
accepts either `edited` as its whole source or explicitly connected track outputs.
Coordinate processing, comparison and export consume `coordinates`. The whole
package is the lossless five-track save; a coordinate file preserves only its
polymer and actual atoms.

Original structure packages are copied under `structures` records with independent
record `id`, selected `object`, `format`, retained `entry`, and `files` mapping
original keys to retained keys. Other source packages use `sources` records. All
necessary files, including original research files and other structure components,
remain available after deletion of the source project. A downstream consumer needs
only the current tracks and relevant explicit correspondence, not editor history.

## Inputs

The optional `source` accepts sequence, structure-set, prediction,
structure-confidence, `workbench.coordinates`, `workbench.protein`, `workbench.esm3_generation` and
`workbench.joint_generation` packages. Select `object` when a source has multiple
objects. Without a source, `sequence` accepts residue text (`_` for a blank) or an
array of residues and nulls.

For structures, provide `selection:{chains:["A"]}` or explicit `positions` using
the [structure module selection](../structure_io/FORMAT.md#public-structure-processing).
A Studio object has one selected chain. Chain loading includes all its protein
residues, including explicitly mapped unobserved positions; water, metals and
other non-amino-acid components remain in the retained structure and context
view without creating track positions. Users can delete unwanted positions
inside Studio; no residue-range input is required to open the chain.
Optional author `regions` such as `12A,15:20,25:28` narrow the selection without
changing order. Initial `tracks` selects `sequence` and/or `coordinates` (default
both); unselected tracks start blank. Optional `atoms` selects actual atom names.
No hidden original atoms refill cleared coordinates. Alternate locations require
explicit preparation. Existing HELIX/SHEET or mmCIF secondary-structure records
and explicitly mapped upstream secondary structure, SASA and function annotation
values are loaded automatically. Absent values stay null or empty. Studio does
not calculate these tracks. Explicit upstream values take precedence over file
secondary-structure records, including explicit nulls.

Generated source objects expose portable `tracks`, independent of native atom37
or tool-specific tensor layouts. Missing returned tracks start blank; supplied
partial coordinates remain partial. Native source files are retained for reference.

## Editing operations

`workbench.sequence_edit` returns a temporary `edited` delivery and derived display
data. `document_file` and `view_file` use
`host.readPreviewFile(id,"edited",key,{signal})`; a small coordinate-free display
may return `document` inline. `editor.json` contains Studio-only display
rows, one original five-track value map (`baseline`, keyed by row ID), deletion
flags, and explicit random operation records; it is not the scientific entry.
The baseline remains unchanged across accepted saves and reopens. Newly inserted
rows have no baseline entry. No keystroke or cross-session undo history is stored.

Each display row has `id`, `residue`, `coordinates`, `secondary_structure`, `sasa`
and `function_annotations` (a list of labels), plus explicit correspondence and
an optional boolean `deleted`. Deleted rows retain their values for restoration.
Only live rows appear in `edited.json`, target mmCIF and the five track outputs.
`document.sequence` renders blanks as `_`. Independent track selections belong to
the UI session. Updates target only the supplied row IDs and fields:

- `update`: `positions:[id,...]`, `changes` containing one or more of the five row
  fields. Sequence, coordinate, secondary-structure or SASA clearing uses null;
  annotation clearing uses an empty list. Updating a deleted row also restores it.
- `insert`: zero-based gap `index` and `sequence` text or an array. Other tracks
  start blank and new stable IDs are allocated.
- `delete`: current editor `positions` IDs. Rows are marked deleted, with all values retained.
- `restore`: current editor `positions` IDs. Remove the deletion flag without changing track values.
- `replace_rows`: the final ordered editor rows, containing exactly `id`, `deleted`
  and the five value fields. Original rows must remain present, including deleted
  ones. Existing correspondence and baseline values come from the explicit source
  package. Newly inserted IDs are allocated by Studio. This adopts local edits in
  one interaction; it does not send a request for each keyboard event.
- `reorder`: every current position ID exactly once. All row values move together.
- `retain`: a public track name and one-based `indices`. Values outside these
  positions are cleared. Optional `atoms` on the coordinate track retains only
  those actual named atoms; missing requested atoms fail.
- `transform_coordinates`: current position IDs, proper 3×3 `rotation` and a
  three-value `translation`. It transforms current named atoms only.
- `random_insert`: integer `seed`, `count`, inclusive current-gap `start`/`end` and
  optional `alphabet` (default blank). Python `random.Random(seed)` samples distinct
  gaps. Stable IDs are independent of RNG. The accepted actual inserted rows and
  read-only operation record are reused; subsequent edits never resample them.

An ordered `operations` list can replace one interactive `operation`. `update`,
`delete`, `reorder` and transforms may address current one-based `indices` instead
of IDs. A reusable recipe edits each incoming object's actual content, for example:

```json
{"selection":{"chains":["A"]},"operations":[
  {"kind":"insert","index":11,"sequence":"__"},
  {"kind":"delete","indices":[27]},
  {"kind":"retain","track":"sequence","indices":[1,2,3,4,5]},
  {"kind":"retain","track":"coordinates","indices":[1,2,3,4,5,31,32,33,34,35,36],"atoms":["N","CA","C"]}
]}
```

Annotation labels stay attached to stable rows through insertion, deletion and
reorder. Export recomputes inclusive contiguous intervals; discontinuous labels
become separate intervals rather than covering unselected new rows.

## Local structure adoption and session lifetime

The optional `structures` input accepts structure-set and prediction packages.
`workbench.sequence_structure` selects
`structure:{input:"structures",object:"id"}` or
`structure:{retained:"record-id"}`. `adopt_structure` takes explicit
`mapping:[{edit_position,position}]` and `tracks` selecting `coordinates` and/or
`residue`. A real position identifies chain, author number and insertion code,
optionally model and component name. Only selected row values are replaced;
other tracks keep their current values. Selecting retained records reuses their
files. Coordinate transforms also work through this interaction.

The loaded preview is retained through the generic host reference
`{interaction:id,output:"edited"}`. Direct edits and undo/redo use local document
snapshots. Done submits `replace_rows` against that source, validates the effective
protein and receives the final package as the node's `document`, preserving source
bindings and connections. Failure leaves the local document available for retry.
Reopening loads this accepted document. A run emits its current contents without
replaying old operations onto newly delivered upstream data. Use **载入输入** to
explicitly load a delivered upstream package or start from sequence text; Done
accepts that new result and Cancel keeps the previous document. Recipe-only nodes
without an accepted document execute their parameters against the input as usual. Session files are released through host preview
cancellation after use. Normal manual project saving persists accepted workflow
and layout changes.

## Browser implementation

`ui/index.js`, `ui/state.js`, `ui/molecule.js` and `ui/styles.js` are the source.
`npm ci --prefix modules/sequence_edit` installs the pinned 3Dmol.js dependency;
`npm run build --prefix modules/sequence_edit` builds the single module entry
`ui.js` with its browser dependencies and license notices. React is supplied by
the host. The display atom model and inferred secondary structure are temporary
rendering data; scientific tracks are updated only by explicit editing.
