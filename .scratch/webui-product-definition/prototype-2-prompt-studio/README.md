# PROTOTYPE 2 — Prompt Studio information architecture (throwaway)

> Three variants of Prompt Studio, switchable via `?variant=`, on the throwaway `/prototype-2-prompt-studio/` page.

## Decision — adopted 2026-08-29

**Variant B — Residue ledger is the adopted direction for Prototype 2.** Its matrix-first hierarchy is the baseline to carry into subsequent frontend design and implementation. Variants A and C remain in this throwaway prototype only as comparison evidence; they are no longer co-equal candidates.

The decision recorded here is the user's explicit selection. No additional selection rationale is inferred. It settles Prototype 2's information hierarchy, not backend implementation or the detailed operation language assigned to later prototypes.

## Product question

Can a protein researcher always tell which residues are selected, what is being edited, which ProteinPrompt tracks are assigned, and how Layout, Conditions, and Structure modes differ?

This prototype covers sections 3.1–3.6 and 3.8 of `docs/2026-08-29-webui-functional-spec.md`, plus the required whole-Prompt summary. It does not validate the detailed operation language assigned to prototypes 3–5. PDB choice, rendered structure geometry, function labels, values, colors, and connected-model compatibility presentation are visibly marked as illustrative where the functional specification has not decided them.

## Run

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-2-prompt-studio/serve.py
```

Then open <http://127.0.0.1:4180/>. Variant B is now the default.

Variants:

- `B` — **Adopted.** Residue ledger: the shared residue matrix is the primary surface; structure is a narrow synchronized navigator.
- `A` — Comparison only. Tri-pane balance: structure, residue matrix, and joint editor have similar visual authority.
- `C` — Comparison only. Selection lens: a local selection-focused view leads, while a global residue matrix remains visible below it.

All state is in memory and resets on reload. This is deliberately not production architecture and has no backend integration. The floating switcher, raw state inspector, sample Prompt picker, and geometry are prototype-only evaluation controls. Sample scientific content is illustrative unless it is simply identifying the real example proteins 1CRN or ubiquitin.

## Walkthroughs

Normal path:

1. Start with `PDB · 1CRN（示意样本）` so all three synchronized regions are visible.
2. Choose `连续 12–20`, then click a residue in the structure and in the matrix.
3. Use the four direct actions inside the Sequence row: Specify, Mask, Insert (assigned or Mask), and Delete. Each action now has a preview followed by an actual in-memory apply step.
4. Insert two residues and confirm that the shared residue axis, selection, per-track counts, and whole-Prompt length update. The new identities use explicit prototype-only labels such as `A:new1` so the prototype does not decide production renumbering semantics.
5. Preview deletion and inspect the pending-delete marks plus lost-track/function impact; confirm deletion, then use the visible Undo button or `Cmd/Ctrl+Z` to restore the full state.
6. Switch among Layout, Conditions, and Structure and verify that every track stays visible while the right-side details change.
7. Open the whole-Prompt summary and inspect assigned/Mask counts.

Ambiguity-prone path:

1. Switch to `空白 · A36 + B18` or `FASTA · ubiquitin`.
2. Verify that the 3D surface disappears, the matrix expands, and the page explicitly says that missing coordinates are legal rather than required input.
3. Choose `不连续 8–10 + 31–33`; verify the same selection wording appears in the matrix, selection bar, and editor.
4. Try Structure mode and verify it is unavailable with an explicit coordinate explanation; other tracks remain visible.

## Prototype record

Browser walkthrough completed on 2026-08-29:

- Continuous `A:12–20` selection produced nine selected residues in the structure, matrix, selection bar, and joint editor. Clicking `A:5` in the structure and `A:15` in the matrix reduced all synchronized readouts to the same single residue.
- Switching Layout → Conditions → Structure preserved all five visible Prompt tracks. Only the editor details and current editing object changed.
- All four entry states matched the functional baseline: blank defaults to Layout; FASTA, PDB, and existing Prompt default to Conditions. Blank and FASTA removed the 3D surface, expanded the matrix, and stated that no coordinates is a legal Prompt state.
- The dense existing Prompt showed partial assignment counts, a visible chain boundary, sparse coordinates/SS8/SASA, interval ribbons, and consistent source/modified/cleared/new markers.
- Variant B gave the residue matrix 638 px versus 205 px for the structure navigator in the walkthrough viewport. Variant C kept both a local selection lens and the full 69-residue axis, with the same six selected residues in both. These are layout facts, not evidence that either variant is preferable.
- The variant arrows and keyboard `←` / `→` changed the shareable URL parameter. Browser console verification ended with no errors.

Screenshots:

- `variant-a-pdb-selection.jpg` — PDB path after one masked residue has actually been inserted; the Prompt length is 47 and `A:new1` is selected.
- `variant-a-no-coordinates.jpg` — blank multi-chain Prompt with the 3D surface collapsed.
- `variant-b-dense-prompt.jpg` — matrix-first dense Prompt after two assigned residues have actually been inserted.
- `variant-c-selection-lens.jpg` — deletion preview with pending-delete marks on both the local lens and global residue axis, plus the explicit confirmation action.

## Remaining questions after adoption

- Whether Variant B's narrow structure navigator needs width or context adjustments during later frontend implementation.
- Whether the always-visible selection bar plus repeated selection text is the right amount of redundancy.

These do not reopen the A/B/C choice. They require later implementation evaluation and are not inferred from the prototype code or walkthrough. Final colors, icons, function-label vocabulary, scientific parameter values, and compatibility wording remain undecided as required by the functional specification.

## Browser-feedback revision — 2026-08-29

The prototype now applies three cross-variant UI corrections from browser comments:

- Removed the generic Specify / Mask / Keep / Restore intent block from the joint editor.
- Put Specify, Mask, Insert, and Delete directly inside every rendered Sequence row. They now mutate the prototype's in-memory Prompt after an explicit preview/apply step rather than stopping at descriptive text.
- Insert exposes count and assigned-vs-Mask initial Sequence state; all other tracks on new residues begin Mask. Delete marks pending residues, previews lost values and affected Function intervals, updates the shared axis on confirmation, and supports visible or keyboard undo.
- Removed the standalone Visibility row and summary count. Coordinates now display assigned or Mask; temporary 3D viewer hide/show state is surfaced only in the structure viewer and raw prototype state.
- Made Variant C's joint editor span both matrix rows instead of sharing only the short top row. The global matrix now remains in the center column, leaving the delete/insert explanation and confirmation flow readable at a 700 px viewport height.

These are prototype-only changes. No backend, production datatype, Node, Adapter, test, `CONTEXT.md`, or functional-spec change is part of this revision; the separate backend migration is outside this task.

## Functional-spec impact

Prototype 2 now records one product decision: Variant B's matrix-first Residue ledger is the adopted information hierarchy. This decision should be carried into the subsequent frontend specification and implementation work. This throwaway-prototype task intentionally does not edit the backend or formal functional specification.
