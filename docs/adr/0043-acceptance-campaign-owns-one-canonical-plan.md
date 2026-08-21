---
status: accepted
---

# Acceptance Campaign owns one canonical plan

The Acceptance Campaign module owns one immutable canonical tier plan for the
15 real-Provider and source-bound tiers. The plan is the sole representation of
tier identity and order, pytest selector, timeout, zero-skip requirement,
required run labels, lifecycle-receipt requirement, and required Environment
Configuration names. For each source-bound tier it also fixes the exact input,
input digest, and Workflow path. No verifier, wrapper, or configuration table
maintains a parallel tier model.

The plan defines execution and structural completion, not scientific meaning.
Each tier continues to own its exact scientific assertions. The Campaign does
not copy, interpret, or rerun those assertions, and the retained public
observations do not become a second scientific authority.

Preparation binds one clean source revision, one wheel and sdist built from
that revision, the canonical plan, and one private Execution Profile to the
Campaign. The candidate and plan cannot change during execution. Repository
verification remains a separate process and is not added to the Campaign plan,
even when it uses the same Execution Profile.

The Execution Profile is validated once at the Campaign interface. For each
tier, the Campaign projects only the Environment Configuration named by the
plan. The plan and retained results record configuration names and requirements,
not private paths, token contents, or reconstructed shell state.

Execution follows the plan in exact serial order, with one blocking child at a
time and every tier attempted at most once. There is no reordering, xdist,
retry, resume, local rerun, risk scheduling, or result promotion. The first
failed tier terminates the Campaign; interruption records the honest outer
terminal without inventing results for unfinished tiers.

Child execution returns a structured outcome through the Campaign-owned seam.
That outcome identifies the tier, source revision, retained location, required
run labels, lifecycle receipt, and verification conclusion. Standard output is
diagnostic only and is not parsed to discover or authorize a retained result.
The retained-result format, including JUnit where the tier declares it, is
admitted once at this seam. Completion, summary, and redacted diagnostics are
projected from that same admitted outcome. Console text, literal warning
matches, and an interpreter executable digest are diagnostics only; none can
authorize or deny an Acceptance Result.

An Acceptance Result exists only after the tier's scientific assertions pass
and its structured outcome satisfies the plan's exact completion contract. A
failed or interrupted tier may retain diagnostic verification output, but that
output is not an Acceptance Result and cannot contribute to Campaign
completion. The Campaign validates structural completion centrally without
reinterpreting scientific content.

The Campaign state is closed: prepared, running, passed, failed, or interrupted.
A Campaign is passed if and only if all 15 tiers produce complete Acceptance
Results in canonical order. Retained observations support inspection; they do
not introduce an evidence manifest, checksum graph, promotion protocol, or
second integrity authority.

Subprocess and filesystem behavior remain internal seams where existing tests
need controlled implementations. No new runner interface is introduced for a
hypothetical Adapter. Tests cross the Campaign interface and verify the unique
plan, profile projection, fixed candidate, exact source-bound assets, structured
outcome handoff, serial once-only execution, first-failure termination,
interruption, and the exact passed condition. Tier tests retain ownership of
scientific assertions.

The existing duplicate tier representations, parallel Provider and source-bound
configuration maps, standard-output result-path grammar, and wrapper-level
completion checks are replaced rather than layered. No compatibility interface,
alias, dual path, or legacy parser is retained.

The rejected alternatives are distributing tier facts across the Campaign and
verifier, treating stdout as a child-result interface, admitting failed
diagnostics as Acceptance Results, moving scientific assertions into the plan,
making repository verification another Campaign tier, persisting private
Execution Profile values, adding retry or resume semantics, constructing a
digest graph around retained observations, treating warning text or interpreter
identity as completion authority, parsing the same JUnit result in multiple
layers, and introducing a runner seam with only one real Adapter.

This decision deepens and refines ADR-0040 without creating an Acceptance
Campaign Plan domain term.
