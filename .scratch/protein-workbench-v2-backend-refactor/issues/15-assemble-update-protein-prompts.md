# 15 — Assemble and update ProteinPrompts

**What to build:** A Workflow can combine aligned residue tracks and function annotations into a validated ProteinPrompt and update its sequence through generic prompt-authoring Nodes, without depending on an ESM-3-specific helper or undeclared payload fields.

**Blocked by:** 14 — Consolidate residue layout and track editing.

**Status:** ready-for-agent

- [ ] Prompt assembly, function annotation, and generic prompt sequence update each have one v2 Node Definition in the existing `prompt_authoring` package.
- [ ] Prompt assembly accepts only declared layout, sequence, structure, visibility, secondary-structure, SASA, and function-annotation inputs with exact Port contracts.
- [ ] All present tracks have the same effective residue layout and legal symbol/value domains; incomplete optional tracks remain explicit rather than being synthesized from UI-only fields.
- [ ] Function annotations validate label, interval, chain/layout correspondence, ordering, and overlap semantics and retain canonical provenance.
- [ ] Sequence update preserves every unaffected track and residue identity while rejecting incompatible length or illegal residue changes.
- [ ] The former ESM-3-specific prompt sequence helper is absorbed as a generic scientific operation rather than retained as duplicate package glue.
- [ ] Node and Binding parameters contain only accepted scientific choices; credentials, device, model, endpoint, and runtime paths are absent.
- [ ] Canonical fixtures prove that ProteinPrompt scientific intent survives codec round-trip and the later ESM-3 adapter boundary.
- [ ] All three Nodes pass the common Contract Test Kit and are discoverable from source and installed artifacts through one package registration.
