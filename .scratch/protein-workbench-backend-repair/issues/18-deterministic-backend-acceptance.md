# 18 — Prove deterministic backend acceptance through REST and WebSocket

**What to build:** A fast provider-backed fixture proves the complete backend contract through the same REST, run-scoped WebSocket, manifest, and artifact interfaces that a future frontend will consume.

**Blocked by:** 17 — Ship an installable backend with source-checkout parity.

**Status:** completed

- [x] The acceptance client submits the canonical Workflow through REST, observes monotonically ordered events, and retrieves the successful run manifest and fifteen PDB artifacts.
- [x] The acceptance asserts ten ESM3 pairs, ten initial folds, two score objectives, weighted top three, three-by-five ProteinMPNN lineage, fifteen per-sequence scores, fifteen final structures, and matching artifact hashes.
- [x] An incompatible edge is rejected before run creation or provider work.
- [x] Provider failure produces a failed run with structured diagnostics while an unrelated branch may still complete.
- [x] Cancellation, repeated Cache-backed execution, an overlapping same-project request, and traversal-like input each satisfy their documented contracts.
- [x] The acceptance uses no current React frontend behavior and therefore freezes a frontend-independent backend contract.
- [x] JUnit output and a command transcript are retained with the deterministic acceptance result.
