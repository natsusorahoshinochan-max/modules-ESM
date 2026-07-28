# 09 — Replay project-scoped typed results

**What to build:** Repeating the same scientifically identified computation within one Project can safely replay complete typed results and stable Candidates, while changed scientific identity, another Project, or ambiguous provenance can never reuse them.

**Blocked by:** 06 — Close dispositions across branch failures.

**Status:** ready-for-agent

- [ ] Result Identity uses the `protein-workbench-cache/v2` namespace and includes every result-affecting Node, Port, Binding, Method, implementation, model, source, input, parameter, randomness, Metric, Context, and Utility contract.
- [ ] Project ID, Run ID, Node Instance ID, timestamps, credentials, private paths, presentation metadata, and performance-only choices do not enter Result Identity.
- [ ] Candidate identity is run-independent and derives from producer Result Identity, output/sample slot, parent Candidate identities, and content digest rather than from Run UUID or content alone.
- [ ] Cache lookup remains after all selected-Binding Readiness checks, and a hit produces succeeded/cache-replayed disposition without an Operation Attempt or Engine Invocation.
- [ ] Physical storage remains Project-scoped and contains only complete, successful, validated, cache-eligible values encoded by the registered Port Type codec, never filesystem paths.
- [ ] Failed, cancelled, interrupted, outcome-unknown, partial, uncontrolled-stochastic, insufficiently identified, or required-standalone-artifact results are not cached.
- [ ] Missing result-affecting identity disables cross-Run caching; the same Result Identity with conflicting output or contract metadata returns `cache_identity_conflict` without overwrite or first-write-wins behavior.
- [ ] Replay preserves Candidate identity and lineage and records current-Run materialization plus producer provenance without copying historical Availability, Readiness, Operation, or Invocation facts.
- [ ] Tests cover deterministic hits, identity-changing misses, Project isolation, typed-codec corruption, path rejection, and conflict handling through public projections.
