# PROTOTYPE 1 — Workflow canvas (throwaway)

> Three variants of the default Workflow and Blender-style node canvas, switchable via `?variant=`, on the throwaway `/prototype-1-workflow-canvas/` page.

## Product question

When every ordinary Node parameter group starts closed and a whole canvas entry can collapse to its name alone, is the Workflow still readable, and can a protein researcher distinguish ordinary Nodes from the “编写 ProteinPrompt” specialized composition without a tutorial?

This prototype covers sections 1 and 2 plus the Prompt Studio opening seam in section 3.2 of `docs/2026-08-29-webui-functional-spec.md`. It is aligned with `docs/2026-08-31-prompt-authoring-layer-and-parameter-ownership-spec.md`: the Palette exposes ordinary Nodes and one specialized ProteinPrompt entry, while materialized managed members are inspection-only. Model names, default scientific parameters, colors, category names, and the meaning of “recommended” remain illustrative where the functional specification has not decided them.

## Run

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-1-workflow-canvas/serve.py
```

Then open <http://127.0.0.1:4179/?variant=A>.

Variants:

- `A` — Graph cards: conventional spatial canvas with ports on the card edges.
- `B` — Signal spine: ports and data types form a strong horizontal reading axis.
- `C` — Lab bench: node bodies read like compact instrument panels.

All state is in memory and resets on reload. This is deliberately not production architecture and has no backend integration.

The managed members shown in the default ProteinPrompt card are an instance-level, read-only projection of that example composition's PDB materialization, including exact Node Type contracts and example parameters. They are not a static type directory or additional Palette entries, and they cannot be selected, edited, copied, or deleted independently. A newly added blank composition therefore starts with no materialized members or fabricated 1CRN summary. The dedicated “编辑 ProteinPrompt” button represents the transition to the full-screen Prompt Studio; this canvas prototype intentionally stops at that boundary.

The default PDB source is materialized inside the composition (`import_structure → select_chains → resolve_residue_axis → prompt_from_structure`) rather than connecting a raw `protein.structure` value to the specialized entry. The card exposes the exact optional `sequence_source`, `structure_source`, and `prompt_source` input Ports plus `protein_prompt` and `residue_layout` output roles; blank needs no input Port. `residue_layout` remains a read-only typed connection role, not a field, track, generic parameter, or Prompt Studio editing control.

Quick contract checks:

1. The Palette and canvas search contain ordinary Nodes plus “编写 ProteinPrompt”; managed member contract names do not appear as addable results.
2. The ProteinPrompt card has no generic parameter form. Its only editing affordance is “编辑 ProteinPrompt”.
3. Selecting, copying, pasting, or deleting the card acts on the complete specialized composition. Paste explicitly records that the backend assigns a new opaque composition identity.
4. The managed-member rows are read-only instance inspection content with exact parameters and no independent canvas selection or action controls.

The connection data-type labels are a prototype hypothesis for preserving readability when whole entries are collapsed. They are not an accepted product decision. The floating switcher, throwaway flag, and raw state inspector are localhost-only evaluation controls and are not part of any variant.

## Decision — 2026-08-29

The user selected **Variant A · Graph cards** as the structural direction for the future Workflow canvas. This settles the overall information hierarchy: a conventional free spatial canvas, a persistent left Authoring Palette, Ports on card edges, ordinary Node controls stacked inside each Node Instance, and a dedicated editor entry inside specialized compositions.

No additional selection rationale was provided, so none is inferred here. The choice does **not** settle whether connection data-type labels should become product behavior, nor any final colors, icons, category names, or density. Variants B and C remain only as primary-source comparison material.

There is no production WebUI route yet. The winner therefore cannot be folded into real frontend code during this prototype stage; it must be rewritten under production constraints when that implementation begins.

## Contract alignment — 2026-08-31

The existing A/B/C prototype was updated in place because it has not been absorbed into a product implementation. All three visual directions now use the same authoring roles and ownership rules:

- ordinary Nodes retain their generic model and parameter controls;
- “编写 ProteinPrompt” is a specialized composition with a dedicated Prompt Studio entry;
- Palette and search never offer managed members;
- managed members, when rendered, are read-only;
- copy and delete operate on the complete composition and its managed members.
