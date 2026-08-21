---
status: accepted
---

# Run Evidence Ledger owns its typed fact grammar

Each Run has one deep Run Evidence Ledger module and no cross-Run or generic
event-store authority. Its current 17 logical fact kinds preserve the distinct
scientific meanings of Run scope, Availability, admission, Readiness,
cancellation, Node Execution Attempt, Operation Attempt, Engine Invocation,
Typed Output and Artifact publication, Node disposition, Selection conclusion,
and Run Closure. Deepening the module hides this grammar from callers; it does
not collapse those meanings into one generic fact.

The Ledger interface accepts complete legal causal transitions. Callers choose
the domain conclusion that occurred but do not supply fact-type strings,
arbitrary payload dictionaries, logical-fact ordering, sequence numbers,
cursors, or transaction grouping. The Ledger constructs the exact logical
facts and owns their closed schema, causal prerequisites, terminal rules,
atomic transaction membership, reducer change, and public projection. The
Node Execution Attempt module therefore chooses the attempt outcome established
by ADR-0041, while the Ledger alone gives that outcome its valid durable
evidence representation.

The Ledger assembles the atomic Node Outcome Publication transaction and the
atomic Selection-plus-Run Closure transaction. Logical facts retain their
individual monotonic sequences and public meanings; the physical transaction
does not become another public fact. The Ledger also owns physical transaction
sequences, cursor encoding and validation, replay windows, event waiting, and
durable-prefix position.

Validation happens once at the durable-write seam. It is limited to the closed
fact and public schemas, causal consistency, transaction completeness and
ordering, monotonic identity, public redaction, bounded transaction size, and
durable acknowledgement. The closed Engine Invocation provenance grammar,
including its chain, order, and residue-mapping semantics, is also validated
only here. The Engine Invocation recorder and `RunResources` may freeze and
transport the typed provenance value but do not replay that validation. The
Ledger does not revalidate admitted scientific values, handle adversarial
callers, repair Provider payloads, or add coercion, fallback, or retry policy.

A transition is staged and validated, canonically encoded, and durably
published before reducer state is installed or any manifest, JSONL lifecycle,
or WebSocket projection is refreshed. Failure to acknowledge the required
transaction produces evidence_unavailable and prevents success publication.
Failure to refresh a projection after durable acknowledgement cannot alter the
outcome. Every projection is rebuilt only from the Ledger; Cache entries,
immutable-object presence, and projection files are not alternative evidence
sources.

On restart, the runtime validates the current-generation durable transaction
prefix and rebuilds reducer state and projections from it. An unfinished Run
receives only one honest interrupted Run terminal. Missing Engine Invocation,
Operation Attempt, Node Execution Attempt, or Selection terminals are not
reconstructed, inferred, or compensated. An unreadable Ledger fails closed.

The Ledger owns visibility references, not scientific bytes. Project-scoped
immutable objects may exist before a publication transaction, but Typed
Outputs and Artifacts become visible only through committed Ledger facts.
Unreferenced objects have no published meaning and remain collectible.

The transaction-store seam exists because durable acknowledgement,
acknowledgement failure, acknowledged-but-unreadable state, and controlled
ordering require distinct production and test Adapters. Fact construction,
schema validation, reduction, and projection receive no hypothetical seams.
Tests cross the Ledger interface through complete transitions and assert
durable facts, causal order, atomicity, projection, cursors, replay, restart,
and exact failure semantics. They do not build raw facts or mutate private
reducer state. Invalid provenance and causal cases enter only through the
Ledger interface; downstream projection tests use admitted transitions. The
Ledger exposes no raw append, generic commit, alias, or dual publication path.
