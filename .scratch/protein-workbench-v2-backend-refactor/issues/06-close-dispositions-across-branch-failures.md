# 06 — Close dispositions across branch failures

**What to build:** A multi-branch Workflow reaches an auditable terminal state in which a failed Node blocks only its dependent branch, unrelated work continues, and every Execution Plan Node has one authoritative disposition with causally closed evidence.

**Blocked by:** 05 — Run a readiness-gated direct Node.

**Status:** ready-for-agent

- [ ] Every Plan Node receives exactly one immutable disposition: succeeded, failed, blocked, cancelled, or interrupted; successful dispositions distinguish executed from cache-replayed resolution.
- [ ] A scheduled Node creates a Node Execution Attempt, an actual implementation call creates an Operation Attempt, and only crossing a declared scientific engine seam creates an Engine Invocation.
- [ ] Blocked and pre-scheduling-cancelled Nodes create dispositions without false Attempts or Invocations and cite their direct causal upstream facts.
- [ ] A Node failure blocks only downstream Nodes whose required inputs cannot be satisfied; an unrelated branch continues and may succeed.
- [ ] Started Node, Operation, and Invocation records each receive exactly one terminal fact, including failed, cancelled, interrupted, or outcome-unknown states.
- [ ] Engine success followed by decode, normalization, validation, or artifact post-processing failure leaves the Invocation successful while the outer Operation and Node fail.
- [ ] Evidence is schema-checked, causally validated, redacted, durably persisted, and sequenced before publication; evidence commit failure prevents Node success and any Cache write.
- [ ] A Run becomes terminal only after every Plan Node disposition and every started Attempt/Invocation terminal are present and causally closed.
- [ ] Public failure diagnostics are bounded and redacted, and Project/Run scope isolation and safe process cleanup are preserved.
