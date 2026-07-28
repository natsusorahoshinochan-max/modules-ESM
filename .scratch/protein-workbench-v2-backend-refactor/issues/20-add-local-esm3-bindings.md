# 20 — Add local ESM-3 Bindings

**What to build:** A repository maintainer can add local ESM-3 execution for sequence, structure, and paired generation by extending only the existing `esm3` Module Package, while Workflows retain the same scientific Node contracts and explicitly choose the local route.

**Blocked by:** 19 — Migrate remote ESM-3 generation.

**Status:** ready-for-agent

- [ ] Local Bindings reuse the three existing ESM-3 Node Definitions and Produced Observation contracts rather than copying or weakening them.
- [ ] Every local Binding fixes an exact Method, model/checkpoint/source identity, adapter/implementation identity, determinism contract, and cacheability declaration.
- [ ] Model paths, device selection, runtime directories, and performance settings are injected through trusted Binding-scoped Environment Configuration and never appear as Workflow scientific parameters.
- [ ] Startup Availability reports missing runtime or structural prerequisites without eager-loading the model or hiding the remote Binding.
- [ ] Per-Run Readiness verifies resolved model/runtime identities and safe fingerprints before Cache lookup, and replacing a model file or configuration invalidates a previous green result.
- [ ] Local and remote Bindings never auto-select, fall back, or substitute for one another based on Availability; exact Binding identity appears in Workflow Lock, Result Identity, Ledger, and projection.
- [ ] Local execution preserves complete Candidate pairing, track fidelity, effective seeds, Produced Observations, and Engine Invocation evidence established by the remote contracts.
- [ ] Full and partial local dependency failures are isolated to the affected Binding and return structured, redacted diagnostics.
- [ ] CTK, installed discovery, deterministic fixtures, and a required local heavy-model gate prove zero Core modification across all three generation modes.
