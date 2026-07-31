# Restore Protein Workbench v2 acceptance after independent review

Label: wayfinder:map

## Destination

Reach a decision-complete route from the independently reviewed v2 backend to a
repair-ready implementation handoff that closes every confirmed contract,
scientific-semantics, and acceptance-evidence defect. The map ends when nothing
material remains to decide; code execution happens in the subsequent
implementation effort.

## Notes

- Domain language comes from [`CONTEXT.md`](../../CONTEXT.md). Use Node Type,
  Execution Binding, Readiness Attestation, Result Identity, Run Evidence
  Ledger, Candidate, Score Observation, and Selection Objective exactly as
  defined there.
- Primary authority is the checked-in
  [v2 specification](../protein-workbench-v2-backend-refactor/spec.md), its
  [37 ticket contracts](../protein-workbench-v2-backend-refactor/issues/), and
  the current checkout. The durable review input is
  [Independent review findings](review-findings.md).
- This is a planning-only wayfinder map. Do not edit production code, resolve
  implementation tickets, consume provider quota, or regenerate remote evidence
  while working this map.
- Corrective breaking changes to the current v2 contracts are allowed. A
  decision may require new contract versions, new digests, explicit Workflow
  relocking, and regenerated evidence; no compatibility layer is owed to
  behavior already shown to violate the accepted contract.
- A valid scientific input that the locked provider and Port contracts can
  represent must be preserved without semantic loss. If it truly cannot be
  represented, reject it before provider execution with a structured error;
  never silently reinterpret it.
- Each later implementation item must begin with a red reproduction and close
  with focused plus cumulative gates. Fresh remote 3GB1 evidence is a final
  source-bound gate, not a per-fix debugging tool.
- Consult `/domain-modeling` when changing domain boundaries,
  `/diagnosing-bugs` for unresolved causal claims, `/codebase-design` for seam
  placement, `/tdd` for implementation handoff criteria, and `/code-review`
  before final acceptance.
- Resolve at most one non-research child ticket per session. Refer to every map
  and child ticket by its linked title, never by a bare number.

## Decisions so far

<!-- Closed child-ticket decisions are indexed here, one linked gist per line. -->

## Not yet specified

- The exact set of contract/Port/Method version increments and which persisted
  Workflows need an explicit relock cannot be fixed until value, descriptor,
  scientific, and provider boundaries are settled.
- The final implementation-ticket count, ownership boundaries, and serial versus
  parallel execution frontier depend on the resolved coupling between Core,
  Module Packages, and acceptance gates.
- Whether the retained Ticket 37 bundle needs a tracked checksum anchor,
  bundled wheel/sdist bytes, independently recomputed lineage/proof, or
  provider-issued receipts remains fog until the evidence-authority decision.
- Pure maintainability observations may graduate into implementation work only
  where a resolved repair requires them for safety, atomicity, or reviewability.
- The exact credential window and quota budget for the final remote rerun will
  be specified only after all provider-free and installed gates are stable.

## Out of scope

- Frontend or UI work, browser behavior, and the older `UI-001..UI-012` or
  `VER-008` surface.
- New scientific capabilities beyond preserving or explicitly rejecting inputs
  already inside the accepted v2 contracts.
- Compatibility shims for invalid v2 behavior, v1 runtime restoration, or
  preservation of stale Contract Locks.
- Modifying vendored or external provider repositories.
- Opportunistic architecture rewrites or P3 cleanup that is not required to
  close a confirmed defect.
- Live remote-provider execution during wayfinding.
