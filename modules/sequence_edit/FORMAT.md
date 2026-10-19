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
