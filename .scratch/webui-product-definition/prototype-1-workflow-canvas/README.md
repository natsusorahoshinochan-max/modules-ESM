# PROTOTYPE 1 — Workflow canvas (throwaway)

> Three variants of the default Workflow and Blender-style node canvas, switchable via `?variant=`, on the throwaway `/prototype-1-workflow-canvas/` page.

## Product question

When every parameter group starts closed and a whole Node Instance can collapse to its name alone, is the Workflow still readable, and can a protein researcher find parameters, model selection, and connection operations without a tutorial?

This prototype covers only sections 1 and 2 of `docs/2026-08-29-webui-functional-spec.md`. Model names, default scientific parameters, colors, category names, and the meaning of “recommended” are visibly marked as illustrative where the functional specification has not decided them.

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

The connection data-type labels are a prototype hypothesis for preserving readability when whole nodes are collapsed. They are not an accepted product decision. The floating switcher, throwaway flag, and raw state inspector are localhost-only evaluation controls and are not part of any variant.

## Decision — 2026-08-29

The user selected **Variant A · Graph cards** as the structural direction for the future Workflow canvas. This settles the overall information hierarchy: a conventional free spatial canvas, a persistent left Node Type list, Ports on the card edges, and model/Port/parameter content stacked inside each Node Instance.

No additional selection rationale was provided, so none is inferred here. The choice does **not** settle whether connection data-type labels should become product behavior, nor any final colors, icons, category names, or density. Variants B and C remain only as primary-source comparison material.

There is no production WebUI route yet. The winner therefore cannot be folded into real frontend code during this prototype stage; it must be rewritten under production constraints when that implementation begins.
