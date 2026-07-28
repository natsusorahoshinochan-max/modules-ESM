# 19 — Migrate remote ESM-3 generation

**What to build:** A Workflow can perform remote ESM-3 sequence, structure, or paired generation through one cohesive `esm3` Module Package and receive complete, correctly paired Candidates with exact model identity and truthful provider evidence.

**Blocked by:** 15 — Assemble and update ProteinPrompts.

**Status:** ready-for-agent

- [ ] Sequence, structure, and paired generation each have one v2 Node Definition and share the ESM-3 adapter, provider contract, test assets, and package registration.
- [ ] Exact Methods and Bindings fix model/source/scale and execution route; model name is not a mutable Workflow parameter, and credential/endpoint configuration is trusted environment state.
- [ ] The adapter preserves every legal ProteinPrompt track and symbol and translates provider SDK values without changing the Node Type's scientific meaning.
- [ ] Sequence generation publishes complete sequence Candidates, structure generation publishes complete structure Candidates, and paired generation preserves exact sequence-to-structure counterpart identity and lineage for every sample.
- [ ] `track` or generation mode controls the provider operation rather than silently discarding response fields; lossy legacy wrappers are not retained as the public contract.
- [ ] Effective seeds and generation parameters are resolved before Result Identity; candidate order, sample slots, parents, and content digests remain stable across Run and Cache replay.
- [ ] Provider-native confidence outputs are declared through exact Produced Observations and statically normalized where required; invalid or incomplete provider output fails before Candidate publication.
- [ ] Composite sequence/structure operations record their real parent-child Engine Invocations and do not use a fixed historical call count as truth.
- [ ] Deterministic fixtures and a required zero-skip provider gate prove all three modes, ten paired Candidates, readiness-before-call, redaction, and complete terminal evidence.
- [ ] The package passes CTK and installed discovery without an ESM-3 Core dispatch or readiness map.
