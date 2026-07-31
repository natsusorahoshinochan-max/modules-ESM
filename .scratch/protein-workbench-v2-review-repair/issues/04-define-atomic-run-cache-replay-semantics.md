# Define atomic Run, cancellation, Cache, and replay semantics

Type: grilling
Mode: HITL
Status: open
Blocked by: 01

## Question

What atomic state transitions must hold between cancellation, Node scheduling,
Operation/Invocation facts, output publication, Cache visibility, terminal
dispositions, restart reconciliation, and replay framing? Decide the
commit/recovery protocol that prevents post-cancel starts, provisional Cache
poisoning, standalone-artifact replay, duplicate cursors, and dependence of a
Derived Run on mutable authoring state.
