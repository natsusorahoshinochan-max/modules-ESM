# 02 — Execution engine with first stub module

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

**What to build:** Make the workflow actually run. A user adds the stub "Echo" node to the canvas, types a string into its parameter form, clicks Run, watches the node state transition from idle → queued → running → completed, and sees the output appear on the node's output port.

This delivers the execution engine's core behavior: topological sort of the DAG, serial node execution, state machine transitions, output passing to downstream ports, and real-time progress over WebSocket. The stub module proves the `WorkflowModule` interface works end to end without any provider dependencies.

**Blocked by:** 01 — Project scaffold, type system, and module registry.

**Status:** superseded

- [ ] Workflow DAG model in `core/graph.py`: Node (with module ID, version, bound parameters), Edge (from node+port → to node+port). Validation that the graph is acyclic.
- [ ] Topological sort: given a workflow, produce a valid execution order. Error on cycles.
- [ ] `RunContext` dataclass with `project_dir`, `node_id`, `run_id`, `seed`, `temp_dir`.
- [ ] `WorkflowModule` base class with `definition` property and `run(inputs, parameters, context) -> dict` abstract method. Optional `validate(inputs, parameters) -> list[str]`.
- [ ] Serial `Executor`: iterates nodes in topological order, calls `run()`, stores outputs keyed by `(node_id, port_name)`, passes upstream outputs as `inputs` dict to downstream nodes. Node state machine: idle → queued → running → completed / failed / cancelled.
- [ ] Error propagation: when a node fails, mark all direct downstream nodes as blocked. Nodes with no failing upstream dependencies continue executing independently.
- [ ] Stub "Echo" module implemented: takes one `text` input port (type `text`) and one `text` output port. `run()` returns the input text unchanged. Has a `repeat` integer parameter that duplicates the text N times.
- [ ] REST `POST /api/projects/{id}/execute` triggers execution. Returns immediately with a run ID; execution proceeds asynchronously.
- [ ] WebSocket endpoint for execution progress: pushes node state changes (node_id, old_state, new_state) and final run completion/failure events.
- [ ] UI: "Run Workflow" button in toolbar. Each node shows its current state with color-coded badge (idle=gray, queued=blue, running=yellow, completed=green, failed=red, blocked=dark-gray).
- [ ] UI: parameter form auto-generated from Echo module's `definition.yaml` (text input for the `repeat` integer parameter).
- [ ] Tests: executor runs single node, executor runs linear chain (A→B→C), executor handles branch (one output→two downstream), executor handles merge (two upstream→one downstream), failed node blocks downstream but not unrelated branch, stub Echo module `run()` contract.
