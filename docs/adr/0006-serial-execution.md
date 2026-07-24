# Serial execution engine

The execution engine runs nodes one at a time in topological order. Branching and
merging are supported, but no two nodes execute concurrently.

Layer-parallel execution was considered and rejected: this machine has performance
constraints that make parallelism unsuitable. Serial execution is simpler to
implement, debug, and reason about, and it avoids subtle concurrency bugs around
shared project state, cache writes, and output file I/O.
