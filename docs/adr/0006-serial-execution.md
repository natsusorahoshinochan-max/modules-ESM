---
status: accepted
---

# Serial execution engine

The execution engine runs nodes one at a time in topological order. Branching and
merging are supported, but no two nodes execute concurrently.

Serial execution matches the target machine's performance constraints and keeps
Project state, Cache writes, evidence publication, and output I/O under one
deterministic execution order.
