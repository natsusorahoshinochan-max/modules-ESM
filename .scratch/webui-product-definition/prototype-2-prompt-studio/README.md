# PROTOTYPE 2 — Prompt Studio information architecture (throwaway)

> Three Prompt Studio layouts, switchable via `?variant=`, on the throwaway `/prototype-2-prompt-studio/` page.

## Decision — adopted 2026-08-29

**Variant B — Residue ledger remains the adopted direction.** Its matrix-first hierarchy is the baseline. Variants A and C remain comparison views; the 2026-08-31 contract-alignment revision updates the existing prototype in place and does not create another prototype.

The decision settles information hierarchy, not production architecture. The prototype remains an in-memory interaction stub.

## Product question

Can a protein researcher always tell which chain/residue locators are selected, what is being edited, which ProteinPrompt tracks are assigned, and how ordered-residue, Conditions, and Structure modes differ?

This revision aligns the prototype with `docs/2026-08-31-prompt-authoring-layer-and-parameter-ownership-spec.md`:

- all four entries represent the same backend `open` behavior;
- UI labels use human-readable chain/residue locators and never expose internal layout/mapping objects, canonical backend addressing, or opaque authoring handles;
- inserted-residue handles are returned by a backend-preview stub rather than allocated as visible synthetic identity labels;
- residue and scalar-track projections use exactly `source`, `current`, `changed`, `cleared`, `inserted`, and `pending-delete`;
- Function annotations correspond only by the full `(label, start, end)` tuple and therefore use only `source`, `inserted`, or `pending-delete`;
- Function tuples keep multiset occurrence semantics: duplicate source occurrences produce duplicate tombstones, while an inserted occurrence remains `inserted` even when its tuple text matches a source occurrence;
- saving is an explicit `open → preview → apply(replace)` flow using a confirmed preview digest;
- preview diagnostics are returned together and include chain/residue locators.

## Run

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-2-prompt-studio/serve.py
```

Then open <http://127.0.0.1:4180/>. Variant B is the default.

Variants:

- `B` — **Adopted.** Residue ledger: the shared locator matrix is the primary surface; structure is a narrow synchronized navigator.
- `A` — Comparison only. Tri-pane balance: structure, residue matrix, and joint editor have similar visual authority.
- `C` — Comparison only. Selection lens: a local selection-focused view leads while the global locator matrix remains visible.

All state is in memory and resets on reload. The floating switcher, sanitized state inspector, sample Prompt picker, digest, diagnostics, and geometry are prototype-only evaluation controls. Sample scientific content is illustrative unless it identifies the real example proteins 1CRN or ubiquitin.

## Walkthroughs

Normal path:

1. Start with `PDB · 1CRN（示意样本）`; the structure, locator matrix, and joint editor are synchronized.
2. Choose `连续 12–20`, then click a locator in the structure and matrix.
3. Use Specify, Mask, Insert, and Delete in the Sequence row. The operation immediately updates the matrix and right panel as an un-applied preview; there is no separate Preview button.
4. Insert two residues. The preview owns the opaque handles; the UI only shows their current ordered chain/residue locators and marks them `inserted`.
5. Preview deletion. Inspect the `pending-delete` projection, lost-track and Function-tuple consequences, and the complete localized diagnostics list; then apply or cancel. After applying deletion of a source residue, its source locator remains in the matrix as a read-only, struck-through `pending-delete` evidence column while the current Prompt count and ordered locators reflect the deletion. Session-inserted residues disappear without a tombstone when deleted. A Function tuple is tombstoned only when its exact start or end residue is deleted; deleting an interior residue preserves the tuple and recomputes its displayed locator.
6. Open an existing Prompt to inspect all six residue/scalar-track states. In Function, apply replacement and verify that the old full tuple is retained as `pending-delete` while the new full tuple is `inserted`—there is no Function `changed` state. Function apply participates in Undo and dirty state.
7. With no local operation preview open, click `保存`; the system automatically requests the normalized backend preview and displays its digest, six-state counts, tombstones, summary, and diagnostics. Confirm replace to return the next Workflow Draft revision and clear completed session tombstones.
8. Cmd/Ctrl-select locators from two chains and try to add a Function tuple. The local preview returns a localized same-chain `error`, disables local apply, and blocks Save. Cancel that un-applied proposal and verify that the unchanged document can be saved normally. A same-chain interval remains applicable.
9. With a save preview already open, create any local operation preview. Both save-confirmation controls are disabled until the local preview is applied or closed, so a stale digest cannot be confirmed.
10. Click a matrix cell and use arrow keys to move the keyboard focus. Type a standard amino-acid letter in Sequence, an SS8 code in Secondary structure, a non-negative number in SASA, or a label over a Function ribbon. `Space` toggles Coordinates Mask/unmask when the exact source coordinates still exist in the current session. Every input immediately updates the un-applied preview; `Enter` applies and `Esc` cancels.
11. Focus any current residue and press `+` to immediately preview an insertion after that anchor. Ghost columns appear in the shared matrix. Digits set the count. One amino-acid letter repeats across all inserted residues; a pasted multi-letter sequence must match the count. With no sequence text, the new Sequence values are Mask. Apply selects the inserted residues while all other tracks start as Mask.
12. Open `状态图例` from the matrix control strip when needed. The former full-width legend/footer and duplicate selection readout were removed, so the matrix surface now ends at the track content instead of reserving the full workspace height.

No-coordinate path:

1. Switch to `空白 · A36 + B18` or `FASTA · ubiquitin`.
2. Verify that the 3D surface disappears and the matrix expands; missing coordinates remain a legal Prompt state.
3. Choose `不连续 8–10 + 31–33`; the same locator wording appears in the matrix, selection bar, and editor.
4. Try Structure mode. It is unavailable with an explicit coordinate explanation while the other tracks remain visible.

## Contract-alignment revision — 2026-08-31

The existing Variant B layout and all four entry paths were retained. The implementation was deliberately kept lightweight:

- opaque authoring handles exist only inside the stub and are removed from the visible state inspector;
- ordered locator labels are derived from the backend-style projection;
- inserted residues use the exact preview-returned handles when the user confirms the operation;
- diagnostics appear as one localized list instead of exception-by-exception interruption;
- an un-applied local proposal blocks both creating and confirming a save preview, so it neither leaks diagnostics into the normalized document nor permits a stale digest to be applied; after local apply, only applied-operation diagnostics appear in a newly generated save preview;
- an `error` diagnostic disables the apply action for the preview that returned it;
- save first displays backend preview output, then requires explicit confirmation before the mocked `apply(replace)` writes back to Workflow;
- keyboard editing uses a visible focus ring and directly maintains the single un-applied preview; there is no separate keyboard-draft or request-Preview step;
- direct-entry keys and visible row operations share the same immediate-preview/apply contract, including tuple-level Function replacement and backend-owned insertion handles;
- Coordinates `Space` restores only exact source coordinates retained in the current edit session; after `apply(replace)` rebases a Mask value as source, the UI refuses to fabricate coordinates;
- the six-state legend is a compact disclosure in the control strip and the duplicate matrix-footer selection text is removed;
- old screenshot references were removed because those images contain superseded visible identities and four-state terminology.

No backend, production datatype, Node, Adapter, test, or `CONTEXT.md` change is part of this prototype revision. The functional specification records the settled keyboard contract.

## Remaining questions

- Whether Variant B's narrow structure navigator needs width or context adjustments during production implementation.
- Whether the always-visible selection bar plus repeated locator text is the right amount of redundancy.

These questions do not reopen the A/B/C decision. Final colors, icons, function-label vocabulary, scientific parameter values, and compatibility wording remain undecided.
