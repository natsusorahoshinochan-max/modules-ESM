# 19a — Named port handles on workflow nodes

**What to build:** When a workflow is opened or a node is added, each node displays named connection handles matching its module's input and output ports. Edges from the workflow JSON (or manually drawn) render as visible, connected lines between the correct ports. Replaces the current ReactFlow `type: "default"` node with a custom component that reads the module definition and renders `Handle` elements per port.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Custom ReactFlow node component that renders `Handle` elements per module input/output port, with port names as handle IDs
- [ ] Handles positioned on left (inputs) and right (outputs) of the node, stacked vertically
- [ ] Port display names shown as labels next to handles
- [ ] Opening a saved project renders edges with correct source/target handle IDs matching port names
- [ ] Manually drawing a connection between two nodes automatically selects the correct handles (or prompts user to pick)
- [ ] The 3GB1 seed workflow opens with all 31 edges visibly connected between correct port handles
- [ ] Backward compatible: existing projects without saved edges still work
- [ ] No regression in node add/remove/reconnect UX
