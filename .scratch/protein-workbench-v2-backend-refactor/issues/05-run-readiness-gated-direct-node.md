# 05 — Run a readiness-gated direct Node

**What to build:** A client can start a compiled Workflow containing one deterministic direct Node, observe exact Binding readiness before any work begins, receive a trustworthy successful Run Projection, and retrieve its validated typed output or artifact through the public protocol.

**Blocked by:** 04 — Compile contract-locked v2 Workflows.

**Status:** ready-for-agent

- [ ] Start Run binds an exact Project, Workflow revision, Contract Lock, compile identity, and FrozenCatalog before execution.
- [ ] Trusted Environment Configuration supplies credentials, endpoints, devices, binaries, and runtime paths by Binding scope without persisting secrets or private paths in the Workflow or public evidence.
- [ ] Every distinct selected Binding receives a Run-scoped Readiness Attestation before implementation construction or any Cache lookup; repeated Nodes using the same exact Binding may share that Run attestation.
- [ ] Availability, Readiness, and Engine Invocation are recorded as different facts and cannot substitute for one another.
- [ ] Volatile prerequisites are re-observed per Run, while reusable proof requires declared identity, scope, maximum age, configuration fingerprint, and invalidation behavior; stale-green mutation tests fail.
- [ ] The direct Node executes through its lazy factory using only the Execution Plan, FrozenCatalog, Environment Configuration, and project-scoped Run resources.
- [ ] Input and output validators run at the Port boundary, and only complete canonical output can produce a successful Node Disposition or public typed result.
- [ ] The success path durably records the minimum causal Ledger facts, exposes a consistent Run Projection and event sequence, and retrieves artifacts only through opaque projection references with scope and digest validation.
- [ ] Run workspace containment, ownership, no-follow, mode, symlink resistance, redaction, and cleanup-error precedence remain enforced.
