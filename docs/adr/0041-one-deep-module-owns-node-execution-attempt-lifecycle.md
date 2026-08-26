---
status: accepted
---

# One deep module owns the Node Execution Attempt lifecycle

Run scheduling owns serial traversal of the Execution Plan, required-input
blocking, cancellation before scheduling, committed-value propagation,
Selection conclusions, and Run Closure. Once a Node Instance is schedulable,
one Run-scoped deep runtime module owns preparation and the complete Node
Execution Attempt lifecycle. Node Execution Attempt, Operation Attempt, Engine
Invocation, Binding Failure, Node Outcome Publication, and Run Closure retain
their distinct scientific and causal meanings.

Input admission, Project Input resolution, and effective-randomness resolution
occur before attempt evidence begins. A local scientific or causal invariant
violation fails fast without inventing an Attempt or Invocation. After
preparation succeeds, the module owns Result Identity, Cache lookup or replay,
Run-scoped Readiness, Operation execution, Engine Invocation recording, output
admission, temporary-resource cleanup, cancellation at the actual causal depth,
and Node Outcome Publication.

Startup Availability is diagnostic only. The module may publish or display it
but never uses it to reject execution or skip a fresh Readiness check. On the
first Cache miss or bypass for one Adapter-route Binding, the module checks
Readiness once and shares that conclusion for later attempts using the same
Binding in the Run. Cache replay does not require Provider Readiness. Direct
routes enter their Operation without Provider Readiness. Only a failing fresh
Readiness conclusion produces Binding Failure before an Operation starts.

Readiness checks actual Environment and Provider operability. It does not hash
source, checkpoints, models, or installation trees; prove PEP 610 or Git state;
or capture programming errors with a broad catch. Programming errors and local
invariant violations fail fast.

A Node Execution Attempt ends only when one Run Evidence Ledger transition
durably commits the required Operation terminal, if any, published Typed Outputs
and Artifacts, Node terminal, and disposition. The Ledger remains the sole
writer of causal facts, durable persistence, reduction, and public domain
projection. The optional Cache replay index is written only after committed
success and cannot alter that outcome.

Cancellation before an attempt starts produces only a Node disposition.
Cancellation after an attempt starts closes only the causal records that
actually started. An Engine Invocation's terminal is never rewritten to match
an outer cancellation or failure. Cleanup failure is recorded at its actual
causal depth; the runtime does not repair, retry, or guess scientific outcomes.

Execution consumes the resolved stable-ID Plan without querying the Catalog
again. Scientific operations receive admitted provider-independent values;
Provider translation stays inside each Adapter; Candidate lineage, residue
mapping, units, masking, Metric meaning, effective randomness, and Result
Identity keep their scientific owners.

The module exposes only a committed Node disposition and, on success, the
published outputs needed by scheduling. Raw Ledger facts, Cache details,
publication preparation, and cleanup choreography remain internal. Internal
state is typed for normal control flow but is not treated as an adversarial
closed wire protocol.
