---
status: accepted
---

# Node outcomes publish atomically through immutable value objects

One successful Engine Invocation can still end in a failed Operation Attempt
during decoding, normalization, output admission, or artifact contract
processing. Once those steps finish, the Operation Attempt has succeeded; the
remaining work is Node Outcome Publication. Failure to persist value objects,
or the admitted Node Result Manifest, can therefore durably fail the Node
Execution Attempt without rewriting the successful Operation Attempt as failed.
Inability to commit the required Ledger evidence instead leaves the outcome
unavailable until the durable prefix can be resolved.

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
sequences, and is recorded by one file publication. Public
lifecycle events continue to use the logical facts and their individual
sequences; the transaction is not exposed as one collapsed lifecycle fact.

Result Identity remains the scientific Cache key. Cache entries are optional
post-commit replay indexes over admitted objects and cannot change a committed
Node outcome. The project trusts conforming deterministic Bindings and does not
maintain a second cross-Run Result Identity authority or conflict failure.

Run Closure records the terminal result of normal execution. On process
restart, an unfinished Run receives one `interrupted` terminal without guessing
missing Engine, Operation, Node, or Selection outcomes. A normal run still
applies the normal Run Closure rule.

The public Run Projection exposes bounded Typed Output descriptors with value
counts and immutable value-manifest references, never embedded scientific
values. A Run-scoped retrieval route returns one exact canonical Port value on
demand. There is no embedded/reference dual path. Artifact retrieval remains a
separate public contract, and WebSocket lifecycle events remain free of large
scientific payloads.

Run Ledger schema `5.0.0`, Cache entry schema `v5`, and public protocol bundle
`2.3.0` are the current schemas. Result Identity uses the
scientific `protein-workbench-cache/v3` namespace because storage
representation does not change scientific identity. Only the current schemas
are admitted. Result Identity inputs, Project-scoped Cache, and replay
provenance are scientific contracts; Result Identity is not a conflict
authority.
