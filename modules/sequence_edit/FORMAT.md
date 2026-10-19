# Sequence and condition editing

`modules.sequence_edit:module` supplies `workbench.edit_sequence`, a React node editor and the temporary `workbench.sequence_edit` interaction. The module reads `workbench.sequence` directly according to its [public format](../folding/FORMAT.md#workbenchsequence); reading either format requires no producer installation.

## workbench.sequence_conditions

The JSON entry is a complete current editing document. It contains an independently allocated `id`, `sequence`, ordered `positions` and `random_operations`. Each position contains:

- `id`: an independently allocated stable position identity.
- `residue`: one uppercase amino acid from `ACDEFGHIKLMNPQRSTVWYBXZJUO`, or `_` for an unspecified residue.
- `fixed`: whether generation must preserve this residue.
- `prompt`: the residue when fixed, otherwise `_`. Changing a fixed residue updates its Prompt. Setting a Prompt amino acid sets that residue and fixes it; setting `_` makes the position variable. An unspecified residue cannot be fixed.
- `coordinates`: `null` or an object mapping atom names to finite XYZ triples in Å. Coordinates remain attached to the position during reordering. They are current accepted values.
- Optional `source`: the explicitly selected input object's `object` ID and one-based `sequence_index`; optional `position` retains its complete original sequence-position record, including real chain, residue number and insertion code when supplied. Inserted positions have no source correspondence.

`sequence` is the concatenation of position residues in their current order. A downstream generator reads `prompt`, `fixed` and coordinates in that same order; it need not reconstruct prior operations or find source files. Sequence insertion creates new position identities; deletion removes those positions and all their current conditions together. Reordering names every current position exactly once.

`random_operations` contains read-only accepted records: integer `seed`, `count`, inclusive current-gap `start` and `end`, insertion `alphabet`, and `actual` records with original `gap`, resulting zero-based `index`, position identity and actual residue. Gap 0 precedes the first residue; gap N follows the last. Each operation samples distinct gaps without replacement with Python's `random.Random(seed)`; count must fit the selected range. The operation record describes that accepted operation. Subsequent deletion, insertion and reordering retain the actual current positions and never replay, refill or resample the record. New random operations use the current document. Identity allocation is independent of the RNG.

Example:

```json
{"id":"editing-object","sequence":"A_C","positions":[{"id":"a","residue":"A","prompt":"A","fixed":true,"coordinates":null},{"id":"inserted","residue":"_","prompt":"_","fixed":false,"coordinates":null},{"id":"c","residue":"C","prompt":"_","fixed":false,"coordinates":{"CA":[1,2,3]}}],"random_operations":[]}
```

## Interaction and confirmation

The interaction accepts an optional `source` package of either format. Multiple sequence objects require the explicit `object` parameter. With no package, `sequence` supplies explicit initial content. The `document` parameter supplies the complete current editing draft for subsequent operations. `operation.kind` is `insert`, `delete`, `update`, `reorder` or `random_insert`; positions are selected by their editing IDs. Invalid or unavailable inputs fail with a specific reason.

The editor loads current content, previews an operation and displays actual positions and conditions. Confirmation receives the exact preview delivery and updates the existing node's `source` binding; an existing source connection is explicitly replaced in the same draft change. Cancel discards the preview. Undo restores the prior document, parameters, input bindings and incoming connection without invoking the random operation again. Confirmation and undo mark the project unsaved; the user saves workflow and layout with the host's save control.

## Structure condition interaction

The editor voluntarily imports the public `read_structure`, `positions`, `atoms`
and `transform` operations from `modules.structure_io`. Both installable module
entries are supplied by the `protein-workbench` distribution; installing the
editing code requires that distribution and its declared `gemmi==0.7.3`
dependency. Structure processing has no editing dependency.

The optional `structures` input accepts `workbench.structure_set` or
`workbench.prediction`. `workbench.sequence_structure` reads this explicitly
selected package and the current `document` (or `source` editing package).
`object` selects one structure object. With no operation it returns the current
edit document and full atom view through temporary files. If `structures` is
unbound, `object` may select one unambiguous retained structure inside the
explicit `source` editing package.

`operation.kind: "adopt_structure"` requires a nonempty `mapping` array of
`{edit_position, position}`. `edit_position` is a current editing position ID;
`position` has actual `chain`, integer `author_number`, `insertion_code`, and
optional `model` and `residue_name`. Each mapping must identify exactly one
component. `tracks` explicitly selects one or more of `coordinates`, `residue`,
and `fixed`. Only mapped editing positions and selected tracks change. Residue
adoption requires an amino acid; fixed adoption fixes the current residue.
Prompt remains consistent with the resulting residue and fixed state. Coordinate
adoption requires unambiguous atom names without alternate locations; explicit
structure preparation is required otherwise.

Accepted documents optionally contain `structures`, each with an independent
`id`, selected `object`, original package `format`, retained `entry` key, and
`files` mapping original package keys to retained editing-package keys. Every
original package file is independently copied, including the complete structure,
components and source research files. Position `structure_position` records the
retained structure ID and complete actual component position. Ordinary sequence
edits retain these files; insertion, deletion and reordering preserve current
position identities and their attached conditions. Source structures remain
independent of adopted coordinates.

`operation.kind: "transform_coordinates"` takes explicit current `positions`,
proper 3×3 `rotation`, and three-value Å `translation`. It transforms current
named coordinates only and fails if a selected position has none. No transform
history is stored or replayed. Clearing uses the ordinary position update with
`coordinates: null`; setting new coordinates adopts those values directly.

Structure interactions return `{document_file, view_file, position_count}` with
output `edited`. Ordinary editing also returns `document_file` when coordinates
or retained structures are present. Read files through
`host.readPreviewFile(preview.id, "edited", key)` before ending the preview.
The UI shows full source atoms separately from current condition coordinates.
Select editing positions and explicit source positions/tracks for local adoption.
Dragging selected coordinates translates them in the displayed XY plane, with
Z projected diagonally. Geometry changes during pointer movement; pointer release
requests the exact backend preview. Confirm receives that preview; cancel restores
accepted coordinates. Undo restores the prior document and input bindings.
Read-only input inspection remains available during a project run.
