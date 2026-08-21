---
status: accepted
---

# One deep module owns the Node Execution Attempt lifecycle

Run scheduling owns serial traversal of the Execution Plan, required-input
blocking, cancellation before scheduling, committed-value propagation,
Selection conclusions, and Run Closure. Once a Node Instance is schedulable,
one Run-scoped deep runtime module owns its preparation and complete Node
Execution Attempt lifecycle. This concentrates the causal state machine behind
one interface while preserving the distinct scientific meanings of Node
Execution Attempt, Operation Attempt, Engine Invocation, Binding Failure, Node
Outcome Publication, and Run Closure.

Input admission, Project Input resolution, and effective-randomness resolution
occur inside that module before attempt evidence begins. A local contract
invariant discovered there fails fast without inventing a Node Execution
Attempt, Operation Attempt, or Engine Invocation. After preparation succeeds,
the module owns Result Identity, Cache lookup or replay, Availability use,
Readiness, Operation execution, Engine Invocation recording, output admission,
temporary-resource cleanup, cancellation at the exact causal depth, and Node
Outcome Publication.

Availability remains an immutable Run admission snapshot. On the first Cache
miss or bypass for one exact Adapter-route Binding, the Run-scoped module
checks Readiness once and retains that conclusion for subsequent Node Execution
Attempts using the same exact Binding. Cache replay does not inspect
Availability or require Readiness. A Binding Failure concludes a Node Execution
Attempt without creating an Operation Attempt.

Readiness maps only an explicit Environment prerequisite or Provider Asset
Closure admission failure to a failing conclusion. Programming errors and local
invariant violations fail fast; a broad catch must not relabel them as Provider
unavailability.

A Node Execution Attempt ends only when one Run Evidence Ledger transaction
atomically commits its required Operation terminal, if any, published Typed
Outputs and Artifacts, Node terminal, and Node disposition. The Ledger remains
the sole writer and owner of fact schema validation, causal validation, durable
persistence, reduction, and public projection. The runtime module determines
which legal transition occurs but does not create another evidence writer.
The optional Cache replay index is written only after committed success and can
never alter that success.

Cancellation before an attempt starts produces only a Node disposition.
Cancellation after an attempt starts closes exactly the causal records that
actually started. An Engine Invocation's real terminal is never rewritten to
match an outer cancellation or failure. Cleanup failure is recorded honestly
as failed or interrupted according to its causal depth; the runtime does not
repair, retry, or guess scientific outcomes.

The deepening does not move scientific meaning. Execution consumes the exact
resolved Execution Plan without querying the FrozenCatalog again. Scientific
operations continue to receive admitted provider-independent values, Provider
translation stays inside each Adapter, and Candidate lineage, residue mapping,
units, masking, Metric meaning, effective randomness, and Result Identity keep
their current contract owners.

The module exposes only a committed Node disposition and, on success, the
published Typed Outputs and Artifacts needed by Run scheduling. Finalization
intents, raw Ledger facts, attempt identities, Cache details, publication
preparation, and cleanup choreography remain inside its implementation. Tests
cross this same interface and assert scientific outcomes and durable causal
evidence rather than private intermediate records.

One closed internal attempt state carries preparation, Cache, Readiness,
Operation, cleanup, and publication facts. Callers do not exchange wide
finalization intents, dispatch internal lifecycle enums, or select cancellation
and error-finalization paths.

The runtime is serial and trusted. It has no concurrency coordination,
retries, fallbacks, compatibility paths, adversarial Provider handling, or
hypothetical seams. It uses only the declared scientific operations, Adapters,
Readiness boundary, and Run Evidence Ledger.
