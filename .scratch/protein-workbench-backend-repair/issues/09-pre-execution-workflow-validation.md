# 09 — Reject invalid Workflows before creating a run

**What to build:** A backend client receives one authoritative validation result before execution, and no provider work or run state is created for a structurally invalid Workflow.

**Blocked by:** 01 — Make backend verification safe, isolated, and tiered.

**Status:** ready-for-agent

- [ ] Validation checks graph acyclicity, Module availability and version, source and target Port existence, and required inputs.
- [ ] Every edge requires an exact source/target type ID match; no implicit scientific conversion is introduced.
- [ ] Duplicate or conflicting input connections are rejected where the receiving Port contract does not allow them.
- [ ] Validation errors identify the relevant Node, Module, Port, and stable error kind without exposing secrets.
- [ ] The REST execution seam rejects an invalid Workflow before allocating a run ID, writing run state, or invoking a provider.
- [ ] A valid Workflow continues to execute serially with unrelated branches preserved after downstream blocking.
