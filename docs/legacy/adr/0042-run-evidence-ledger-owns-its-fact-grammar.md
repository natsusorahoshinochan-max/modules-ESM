---
status: accepted
---

# Run Evidence Ledger owns typed causal evidence

Each Run has one deep Run Evidence Ledger and no cross-Run or generic event-store
authority. Its typed domain facts preserve the distinct meanings of Run scope,
diagnostic Availability, admission, Readiness, cancellation, Node Execution
Attempt, Operation Attempt, Engine Invocation, output publication, Node
disposition, Selection conclusion, and Run Closure. Deepening the module hides
their storage grammar from callers; it does not collapse those meanings into a
generic payload.

The Ledger interface accepts complete legal causal transitions. Callers select
the domain conclusion that occurred but do not supply raw fact-type strings,
logical ordering, sequences, cursors, or transaction grouping. The Ledger owns
causal prerequisites, terminal rules, atomic Node publication, monotonic
sequences, reduction, and typed domain projection.

Validation occurs once at the durable-write seam and is limited to normal causal
consistency, transition completeness, ordering, monotonic identity, durable
acknowledgement, and scientific invocation provenance such as effective
randomness and residue mapping. Internal fact records are not a public wire
protocol: they do not require adversarial duplicate-key handling, redundant
namespace or artifact-kind fields, exact closed field sets, canonical JSON text,
or self-digests merely to prove that the Ledger wrote them.

`workflow_commit_id` is the single durable execution root. Ledger facts do not
repeat Workflow, Catalog, Contract Lock, Plan, Readiness-contract, or attestation
digests. They store the minimum evidence needed to interpret scientific inputs,
effective parameters and randomness, stable Node/Method/Metric IDs, output
identities, residue mappings, lineage, and Observation/Metric/Method
relationships. An actual device may be recorded as non-gating provenance when
known; it does not split Result Identity or Cache identity.

`protein_workbench_public` alone owns REST and WebSocket wire projection and
redaction. It consumes typed Ledger domain projections; it does not decode
durable transactions or define a second fact grammar. Typed public constructors
guarantee the complete response, event, and error shape before serialization.
Production emission does not run the Bundle Schema validator over an already
constructed response.

A transition is durably published before reducer state and projections advance.
Failure to acknowledge required evidence prevents success publication. Public
encoding or delivery failure after durable acknowledgement cannot alter the
domain outcome. Cache entries, immutable-object presence, and projection files
are not alternative evidence sources.

On restart, the Ledger reads the required fields and causal sequence from its
durable prefix and rebuilds state. An unfinished Run receives one honest
`interrupted` terminal without inventing missing internal outcomes. Scientific
value objects retain content-addressed identity and verify their requested
scientific bytes; ordinary Ledger metadata does not inherit that content-proof
contract.

Tests cross the Ledger interface through complete transitions and assert causal
order, atomic publication, typed domain projection, cursors, replay, restart,
and failure semantics. Public protocol tests consume typed domain projections
and events. The Ledger exposes no raw append, generic commit, alias, migration,
or dual publication path.
