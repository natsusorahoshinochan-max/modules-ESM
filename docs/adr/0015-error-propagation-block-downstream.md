# Error propagation: block downstream, allow unrelated branches

When a node fails, its output ports produce no values. The execution engine
marks all direct downstream nodes as blocked rather than queued. Nodes whose
all input dependencies are resolved and whose upstream nodes all succeeded
can still execute, even if other branches of the DAG have failed.

ESMProteinError (returned by the ESM SDK after retries) is treated as a
failure, not a partial result. The node is marked failed with a diagnostic
error message. Modules must not swallow provider errors and return partial
data.

This keeps the execution model simple: each node either produces complete,
valid outputs for every required standalone output port and exactly one
complete alternative from each declared output group, or it fails entirely.
Ports belonging to an unselected output alternative are absent by contract;
they are not partial success. There is no concept of degraded or partial
success within the selected output contract.
