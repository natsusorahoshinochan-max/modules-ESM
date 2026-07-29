---
status: refined by the v2 backend architecture specification
---

# Error propagation: block downstream, allow unrelated branches

When a Node fails, its output Ports produce no values. In the v2 runtime, a
downstream Node is blocked when the absent values leave one of its required
input Ports unsatisfied. An edge into an optional input Port does not by itself
make the downstream Node blocked; it may execute after the upstream disposition
is known, with that optional input absent. Nodes whose required inputs are
satisfied can still execute even if another branch of the DAG has failed.

The legacy v1 scheduler blocked every direct downstream Node after a failure.
The v2 backend architecture specification refines that rule to required-input
satisfiability and requires each blocked disposition to cite its direct causal
upstream dispositions.

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
