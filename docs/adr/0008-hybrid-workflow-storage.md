---
status: superseded by ADR-0037 and ADR-0039
---

# Hybrid project storage: metadata inline, data referenced, UI state separate

This is a historical v1 design. It is non-normative and creates no current
storage or compatibility requirement.

Workflow data is split across three files: workflow.json embeds all metadata
(nodes, module IDs, versions, parameters, and port connections); ui.json stores
canvas-only state (node positions, dimensions, grouping, colors, annotations,
zoom level); large data payloads (sequences, structures, generated candidates)
are stored as separate files under inputs/ and outputs/ with relative path
references in the workflow.

The ui.json / workflow.json split keeps the workflow definition
(pure computation graph) independent of presentation. Two users can share a
workflow.json, load it into their own canvases, and auto-layout the nodes
without needing the original positions. Conversely, ui.json can be discarded
or regenerated without losing any scientific data.

This also keeps workflow.json small and human-readable. Input files are the
originals the user imported. Output files follow the naming convention
{run_id}_{node_id}_{port_name}.json.

Rejected: embedding all data inline (bloated JSON, hard to inspect manually),
storing everything as separate files (loses the single-file portability of
the workflow definition), and combining UI state with workflow state (couples
presentation to computation, breaks sharing and auto-layout).
