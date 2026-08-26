---
status: accepted
---

# Execution evidence separates attempts from engine invocations

A Node Execution Attempt records one scheduled Node Instance outcome. A Cache
hit terminates only that Node Execution Attempt and creates no Operation
Attempt or Engine Invocation. After a Cache miss or bypass, each actual run of
the selected implementation is an Operation Attempt, which may contain zero,
one, or several Engine Invocations.

During normal execution, every Operation Attempt and Engine Invocation that
starts has exactly one terminal fact: `succeeded`, `failed`, `cancelled`,
`interrupted`, or `outcome_unknown`. Successful engine work followed by
decoding, normalization, output validation, or artifact post-processing
failure remains a successful Invocation inside a failed Operation Attempt; its
terminal fact is never rewritten as engine failure. If the process exits, the
next startup closes only the unfinished Run as `interrupted`; it does not infer
or reconstruct missing internal attempt or invocation terminals.

Parent-child invocation roles are explicit. The general Ledger contract does
not impose a global invocation count. A scenario-specific scientific
acceptance test may still require exact counts for its named Provider stages.

The Run Evidence Ledger is the single writer and ordered durable source of
typed run facts. The run manifest, JSONL lifecycle stream, and WebSocket stream
are rebuildable projections of that ledger rather than independent writers or
competing sources of truth.

Each proposed fact passes closed typed-domain schema and causal validation, then
durable persistence with a monotonic run sequence, before it may affect a domain
projection. `protein_workbench_public` alone converts admitted domain projections
to the redacted public REST and WebSocket contract. Public projection failure
after durable acknowledgement cannot change the persisted execution outcome.
Failure to persist required execution evidence prevents the Node Execution
Attempt from publishing success or writing a Cache result.
