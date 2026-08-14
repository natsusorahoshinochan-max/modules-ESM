---
status: accepted
---

# Node outcomes publish atomically through immutable value objects

One successful Engine Invocation can still end in a failed Operation Attempt
during decoding, normalization, output admission, or artifact contract
processing. Once those steps finish, the Operation Attempt has succeeded; the
remaining work is Node Outcome Publication. Failure to persist value objects,
or establish a non-conflicting Result Identity, can therefore durably fail the
Node Execution Attempt without rewriting the successful Operation Attempt as
failed. Inability to commit the required Ledger evidence instead leaves the
outcome unavailable until the durable prefix can be resolved.

All admitted Port values are persisted as immutable Project-scoped,
content-addressed objects before they can become visible. Ordinary Typed
Outputs reference ordered value manifests; Artifact descriptors reference the
same physical object store while retaining their distinct artifact-capable Port
semantics. The Run Evidence Ledger, not object presence, is the authority for
visibility. Unreferenced objects have no published meaning and are safe to
collect.

One physical Ledger transaction contains the independently typed logical facts
that conclude a Node: the Operation Attempt terminal when execution occurred,
Typed Output and Artifact publication facts when successful, the Node
Execution Attempt terminal, and the Node disposition. The transaction is
validated as one causal state transition, receives contiguous logical fact
sequences, and is durably committed by one atomic file publication. Public
lifecycle events continue to use the logical facts and their individual
sequences; the transaction is not exposed as one collapsed lifecycle fact.

A Project-scoped publication lock compares each successful result with the
Result Identity projection derived from committed Ledger publications. Equal
contract and output manifests may publish again; conflicting manifests fail as
`result_identity_conflict`. This invariant is authoritative independently of
Result Cache availability. Cache entries become optional post-commit replay
indexes over the same immutable objects and cannot change a committed Node
outcome.

Run Closure is a separate atomic transaction. It may commit required Selection
terminals together with the Run terminal only after every Node disposition is
durable. Restart reconciliation closes only genuinely open attempts, derives
blocked or interrupted dispositions from the durable prefix, reconstructs
missing Selection conclusions from committed values when possible, and then
applies the normal Run Closure rule. A restart audit fact never forces an
otherwise complete Run to `interrupted`.

The public Run Projection exposes bounded Typed Output descriptors with value
counts and immutable value-manifest references, never embedded scientific
values. A Run-scoped retrieval route returns one exact canonical Port value on
demand. There is no embedded/reference dual path. Artifact retrieval remains a
separate public contract, and WebSocket lifecycle events remain free of large
scientific payloads.

Run Ledger schema `4.0.0`, Cache entry schema `v4`, and public protocol bundle
`2.2.0` are new current-generation schemas. Result Identity keeps the
scientific `protein-workbench-cache/v3` namespace because storage
representation does not change scientific identity. Prior development
artifacts are unsupported and are not migrated, aliased, or replayed.

The rejected alternatives are increasing the Ledger fact-size limit, removing
PAE or reconstruction values, reducing declared sample counts, treating
ordinary typed values as Artifacts, using Cache as evidence, appending terminal
facts sequentially with compensating catches, or coordinating atomic renames
across independently configured Run and output roots.

This decision refines ADR-0030. It supersedes ADR-0036's Run Ledger `3.0.0` and
Cache entry `v3` physical-schema declarations while retaining its
`protein-workbench-cache/v3` Result Identity rules. It supersedes ADR-0031 only
where that decision names the conflict `cache_identity_conflict` and requires
Cache entries to contain copied canonical values; ADR-0031's Result Identity
inputs, Project scope, replay provenance, and fail-on-conflict semantics remain
in force.
